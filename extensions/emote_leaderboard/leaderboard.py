#region Imports
import os
from functools import total_ordering

import hikari
import lightbulb

from database import members, guilds, bot_messages
from hooks import fail_if_not_admin_or_owner
#endregion

#region Loader and Command Group Setup
loader = lightbulb.Loader()
leaderboard = lightbulb.Group("leaderboard", "Emote leaderboard group")
emoji = leaderboard.subgroup("emoji", "Emoji related commands")
#endregion

#region Emote Leaderboard Milestone Functions
MILESTONES = [
    (1, "Beginner"),
    (10, "Novice"),
    (25, "Apprentice"),
    (50, "Adept"),
    (100, "Expert"),
    (250, "Master"),
    (500, "Grandmaster"),
    (1000, "Legendary"),
    (2000, "Mythic"),
    (5000, "Impossible")
]

def get_rank_for_count(count: int) -> tuple[str, int] | None:
    """
    Get the rank title for a given emoji count.

    Args:
        count (int): The emoji count.

    Returns:
        tuple[str, int] | None: The rank title and milestone count, or None if no rank.
    """
    achieved_rank = None

    for milestone, title in MILESTONES:
        if count >= milestone:
            achieved_rank = (title, milestone)
        else:
            break

    return achieved_rank

def check_milestone(old_count: int, new_count: int) -> tuple[str, int] | None:
    """
    Check if a milestone has been reached between the old and new counts.

    Args:
        old_count (int): The previous emoji count.
        new_count (int): The updated emoji count.

    Returns:
        tuple[str, int] | None: The rank title and milestone count if reached, else None.
    """
    for milestone, title in MILESTONES:
        if old_count < milestone <= new_count:
            return title, milestone
    return None

async def update_user_rank(user_id: str, guild_id: int, emoji_id: int | str, count: int) -> None:
    """
    Update the user's rank based on their emoji count.

    Args:
        user_id (str): The ID of the user.
        guild_id (int): The ID of the guild.
        emoji_id (int | str): The ID or name of the emoji.
        count (int): The emoji count.
    """
    account = members.find_one({"id": user_id})
    if not account:
        return

    emote_rank = account.get("emote_rank", [])

    if not isinstance(emote_rank, list):
        emote_rank = []

    rank_info = get_rank_for_count(count)

    found = False
    for entry in emote_rank:
        if entry.get('guild_id') == str(guild_id) and entry.get("emoji_id") == emoji_id:
            if rank_info:
                entry["rank_title"] = rank_info[0]
                entry["rank_threshold"] = rank_info[1]
            else:
                entry["rank_title"] = "Unranked"
                entry["rank_threshold"] = 0
            found = True
            break

    if not found:
        emote_rank.append({
            "guild_id": str(guild_id),
            "emoji_id": emoji_id,
            "rank_title": rank_info[0] if rank_info else "Unranked",
            "rank_threshold": rank_info[1] if rank_info else 0
        })

    members.update_one(
        {"id": user_id},
        {"$set": {"emote_rank": emote_rank}}
    )
#endregion

#region Tracked Emoji Utility Functions
async def get_guild_tracked_emoji(guild_id: int) -> int | str | None:
    """
    Get the tracked emoji of a specific guild.

    Args:
        guild_id (int): The ID of the guild to check.

    Returns:
        int | str | None: The emoji ID (custom) or name (unicode), OR None if not set.
    """
    guild_config = guilds.find_one({"guild_id": str(guild_id)})

    if not guild_config:
        return None

    emotes = guild_config.get("tracked_emoji")

    return emotes

async def set_guild_tracked_emoji(guild_id: int, emoji: int | str) -> None:
    """
    Set the tracked emoji of a specific guild.

    Args:
        guild_id (int): The ID of the guild to set.
        emoji (int | str): The emoji ID (custom) or name (unicode) to set.
    """
    guilds.update_one(
        {"guild_id": str(guild_id)},
        {"$set": {"tracked_emoji": emoji}},
        upsert=True
    )
#endregion

#region Emoji Count Functions

async def increment_emoji_count(guild_id: int, emoji_id: int, user_to_increment: hikari.User) -> tuple[int, int]:
    """
    Increment the count of an emoji in the database.

    Args:
        guild_id (int): The ID of the guild where the emoji was used.
        emoji_id (int): The ID of the emoji to increment.
        user_to_increment (hikari.User): The user whose emoji count is being incremented.
    """

    account = members.find_one({"id": str(user_to_increment.id)})

    if not account:
        raise ValueError("User not found in the database despite getting an emote.")

    # Increment the emoji count for the user in the database
    emote_count = account.get("emote_count", [])

    if not isinstance(emote_count, list):
        emote_count = []

    old_count = 0

    found = False
    for entry in emote_count:
        if entry["emoji_id"] == emoji_id:
            old_count = entry["count"]
            entry["count"] += 1
            found = True
            break

    if not found:
        emote_count.append({
            "guild_id": str(guild_id),
            "emoji_id": emoji_id,
            "count": 1
        })

    members.update_one(
        {"id": str(user_to_increment.id)},
        {"$set": {"emote_count": emote_count}}
    )

    new_count = old_count + 1

    await update_user_rank(str(user_to_increment.id), guild_id, emoji_id, new_count)

    return old_count, new_count

# Emote counter
@loader.listener(hikari.GuildReactionAddEvent)
async def emote_counter(event: hikari.GuildReactionAddEvent) -> None:
    """Track emoji reactions and increment counts for specific emojis."""

    if event.member.is_bot:
        return

    try:
        tracked_emoji = await get_guild_tracked_emoji(event.guild_id)

        if not tracked_emoji:
            return

        emoji_identifier = None
        emoji_display = None

        if event.emoji_id:
            emoji = await event.app.rest.fetch_emoji(event.guild_id, event.emoji_id)
            emoji_identifier = emoji.id
            emoji_display = f"<:{emoji.name}:{emoji.id}>"
            await event.app.rest.add_reaction(event.channel_id, event.message_id, emoji=emoji.name, emoji_id=emoji_identifier)
            print(f"Custom Emoji: {emoji.name} (ID: {emoji.id})")

        else:
            emoji_identifier = event.emoji_name
            emoji_display = emoji_identifier
            await event.app.rest.add_reaction(event.channel_id, event.message_id, emoji_identifier)
            print(f"Unicode Emoji: {emoji_identifier}")

        if emoji_identifier != tracked_emoji:
            return

        message = await event.app.rest.fetch_message(event.channel_id, event.message_id)

        if message.author.id == event.member.id:
            return

        user_to_credit = None

        if message.author.is_bot:
            bot_content = bot_messages.find_one({
                "message_id": str(message.id),
                "guild_id": str(event.guild_id)
            })

            if bot_content:
                creator_id = bot_content["creator_id"]
                try:
                    user_to_credit = await event.app.rest.fetch_user(int(creator_id))
                    print(f"Attributing emote to bot command creator: {user_to_credit.username}")
                except hikari.NotFoundError:
                    return
            else:
                user_to_credit = message.author
        else:
            user_to_credit = message.author

        old_count, new_count = await increment_emoji_count(event.guild_id, emoji_identifier, user_to_credit)
        print(f"Incremented {emoji_identifier} for user {user_to_credit.username} in guild {event.guild_id}")

        milestone = check_milestone(old_count, new_count)

        if milestone is not None:
            rank_title, threshold = milestone

            embed = hikari.Embed(
                title="🎉 Emote Milestone Reached! 🎉",
                description=(
                    f"Congratulations {user_to_credit.mention}!\n\n"
                    f"You have reached the **{rank_title}** rank by receiving "
                    f"**{new_count}** reactions with {emoji_display}!\n\n"
                    f"Keep up the great work!"
                ),
                color=0xFFD700
            )

            embed.set_thumbnail(user_to_credit.display_avatar_url)

            next_milestone = None
            for milestone_count, milestone_title in MILESTONES:
                if milestone_count > new_count:
                    next_milestone = (milestone_title, milestone_count)
                    break

            if next_milestone:
                next_title, next_threshold = next_milestone
                embed.add_field(
                    name="Next Milestone",
                    value=(
                        f"Your next rank is **{next_title}** at **{next_threshold}** reactions. "
                        f"Keep going!"
                    ),
                    inline=False
                )

            await event.app.rest.create_message(
                channel=event.channel_id,
                embed=embed
            )
            print(f"Milestone notification sent: {rank_title} for {user_to_credit.username}")

    except hikari.NotFoundError:
        print("Emoji not found.")
        return

    except Exception as e:
        print(f"Error in emote_counter: {e}")
        return

#endregion

#region Commands - Tracked Emoji
@emoji.register()
class SetTrackedEmoji(
    lightbulb.SlashCommand,
    name="set",
    description="Set the emoji to be tracked for the emote leaderboard in this server.",
    hooks=[fail_if_not_admin_or_owner]
):
    emoji = lightbulb.string("emoji", "The emoji to track for the leaderboard (custom or unicode).")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """
        Set the tracked emoji for the emote leaderboard in this server.
        """
        emoji_input = self.emoji

        # Check if it's a custom emoji
        if emoji_input.startswith("<:") and emoji_input.endswith(">"):
            parts = emoji_input.strip("<>").split(":")
            if len(parts) >= 3:
                try:
                    emoji_id = int(parts[-1])
                    await set_guild_tracked_emoji(ctx.guild_id, emoji_id)
                    await ctx.respond(f"Set the tracked emoji to {emoji_input} for this server.", ephemeral=True)
                    return
                except ValueError:
                    await ctx.respond("Invalid custom emoji format.", ephemeral=True)
                    return
        # Otherwise, treat it as a unicode emoji
        await set_guild_tracked_emoji(ctx.guild_id, emoji_input)
        await ctx.respond(f"Set the tracked emoji to {emoji_input} for this server.", ephemeral=True)

@emoji.register()
class ViewTrackedEmoji(
    lightbulb.SlashCommand,
    name="view",
    description="View the currently tracked emoji for the emote leaderboard in this server.",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """
        View the currently tracked emoji for the emote leaderboard in this server.
        """
        tracked_emoji = await get_guild_tracked_emoji(ctx.guild_id)

        if not tracked_emoji:
            await ctx.respond("No emoji is currently being tracked for the leaderboard in this server.", ephemeral=True)
            return

        if isinstance(tracked_emoji, int):
            emoji_display = f"<:emoji:{tracked_emoji}>"
        else:
            emoji_display = tracked_emoji

        await ctx.respond(f"The currently tracked emoji for the leaderboard in this server is: {emoji_display}", ephemeral=True)
#endregion

#region Commands - Leaderboard Viewing and Ranking

@leaderboard.register()
class ViewLeaderboard(
    lightbulb.SlashCommand,
    name="check",
    description="View the emote leaderboard for all tracked emojis.",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """
        View the emote leaderboard.
        """
        tracked_emoji = await get_guild_tracked_emoji(ctx.guild_id)

        if not tracked_emoji:
            await ctx.respond("No emoji is currently being tracked for the leaderboard in this server. An admin can set one with `/leaderboard setemoji`.", ephemeral=True)
            return

        user_counts = []

        for member_doc in members.find({"emote_count": {"$exists": True, "$ne": []}}):
            emote_counts = member_doc.get("emote_count", [])
            emote_rank = member_doc.get("emote_rank", [])

            for entry in emote_counts:
                if entry.get("guild_id") == str(ctx.guild_id) and entry.get("emoji_id") == tracked_emoji:
                    rank_title = "Unranked"
                    for rank_entry in emote_rank:
                        if rank_entry.get("guild_id") == str(ctx.guild_id) and rank_entry.get("emoji_id") == tracked_emoji:
                            rank_title = rank_entry.get("rank_title", "Member")
                            break

                    user_counts.append({
                        "user_id": member_doc["id"],
                        "username": member_doc.get("username", "Unknown"),
                        "count": entry["count"],
                        "rank_title": rank_title
                    })
                    break

        if not user_counts:
            await ctx.respond("No emote data found for the tracked emoji.")
            return

        user_counts.sort(key=lambda x: x["count"], reverse=True)
        top_users = user_counts[:10]

        if isinstance(tracked_emoji, int):
            emoji_display = f"<:emoji:{tracked_emoji}>"
        else:
            emoji_display = tracked_emoji

        description_lines = []
        for idx, user_data in enumerate(top_users, 1):
            medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"**{idx}.**"
            description_lines.append(
                f"{medal} <@{user_data['user_id']}> - {user_data['count']} reactions\n"
                f"Rank: **{user_data['rank_title']}**"
            )

        embed = hikari.Embed(
            title=f"{emoji_display} Leaderboard",
            description="\n".join(description_lines),
            color=0xFFD700
        )

        embed.set_footer(
            text="Use /leaderboard rank to check your own rank!"
        )

        await ctx.respond(embed=embed)

@leaderboard.register()
class CheckRank(
    lightbulb.SlashCommand,
    name="rank",
    description="Check your rank on the emote leaderboard."
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """
        Check your rank on the emote leaderboard.
        """
        tracked_emoji = await get_guild_tracked_emoji(ctx.guild_id)

        if not tracked_emoji:
            await ctx.respond("No emoji is currently being tracked for the leaderboard in this server. An admin can set one with `/leaderboard setemoji`.", ephemeral=True)
            return

        user_account = members.find_one({"id": str(ctx.user.id)})

        if not user_account or "emote_count" not in user_account:
            await ctx.respond("You don't have any emote data yet!", ephemeral=True)
            return

        user_count = 0
        for entry in user_account.get("emote_count", []):
            if entry.get("guild_id") == str(ctx.guild_id) and entry.get("emoji_id") == tracked_emoji:
                user_count = entry["count"]
                break

        if user_count == 0:
            await ctx.respond("You don't have any emote data yet!", ephemeral=True)
            return

        higher_count = 0
        total_users = 0

        for member_doc in members.find({"emote_count": {"$exists": True, "$ne": []}}):
            emote_counts = member_doc.get("emote_count", [])

            for entry in emote_counts:
                if entry.get("guild_id") == str(ctx.guild_id) and entry.get("emoji_id") == tracked_emoji:
                    total_users += 1
                    if entry["count"] > user_count:
                        higher_count += 1
                    break

        rank = higher_count + 1

        if isinstance(tracked_emoji, int):
            emoji_display = f"<:emoji:{tracked_emoji}>"
        else:
            emoji_display = tracked_emoji

        current_rank = get_rank_for_count(user_count)
        rank_text = f"**{current_rank[0]}**" if current_rank else "Unranked"

        next_milestone = None
        for milestone_count, milestone_title in MILESTONES:
            if milestone_count > user_count:
                next_milestone = (milestone_title, milestone_count)
                break

        description = (f"You are ranked **#{rank}** out of **{total_users}** users for the emoji {emoji_display} with a total of **{user_count}** reactions!\n\n"
                       f"Your current rank: {rank_text}")

        if next_milestone:
            next_title, next_threshold = next_milestone
            remaining = next_threshold - user_count
            description += f"\n\nNext rank: **{next_title}** at **{next_threshold}** reactions ({remaining} more)."

        embed = hikari.Embed(
            title=f"🏆 Your {emoji_display} Rank",
            description=description,
            color=0x3498DB
        )

        embed.set_footer(
            text="Use /leaderboard view to see the full leaderboard!"
        )

        await ctx.respond(embed=embed, ephemeral=True)

#endregion

loader.command(leaderboard)