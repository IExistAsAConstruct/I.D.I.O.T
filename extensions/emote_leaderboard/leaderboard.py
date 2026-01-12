import os
from functools import total_ordering

import hikari
import lightbulb

from database import members, guilds
from hooks import fail_if_not_admin_or_owner

loader = lightbulb.Loader()
leaderboard = lightbulb.Group("leaderboard", "Emote leaderboard group")

#def get_emote_leaderboard_list() -> list[int]:
#    """
#    Retrieve a list of emoji IDs from the environment variable used in local emote leaderboards.
#
#    Returns:
#        list[int | str]: A list of emoji IDs (custom) or emoji names (unicode).
#    """
#    emotes = os.getenv("EMOTE_LEADERBOARD")
#    if emotes:
#        result = []
#        for emote in emotes.split(","):
#            emote = emote.strip()
#            if emote.isdigit():
#                result.append(int(emote))
#            else:
#                result.append(emote)
#        return result
#    return []

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

async def increment_emoji_count(guild_id: int, emoji_id: int, user_to_increment: hikari.User) -> None:
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

    found = False
    for entry in emote_count:
        if entry["emoji_id"] == emoji_id:
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

        if event.emoji_id:
            emoji = await event.app.rest.fetch_emoji(event.guild_id, event.emoji_id)
            emoji_identifier = emoji.id
            print(f"Custom Emoji: {emoji.name} (ID: {emoji.id})")

        else:
            emoji_identifier = event.emoji_name
            print(f"Unicode Emoji: {emoji_identifier}")

        if emoji_identifier != tracked_emoji:
            return

        message = await event.app.rest.fetch_message(event.channel_id, event.message_id)

        if message.author.id == event.member.id: #or message.author.is_bot:
            return

        await increment_emoji_count(event.guild_id, emoji_identifier, message.author)
        print(f"Incremented {emoji_identifier} for user {message.author.username} in guild {event.guild_id}")

    except hikari.NotFoundError:
        print("Emoji not found.")
        return

    except Exception as e:
        print(f"Error in emote_counter: {e}")
        return

@leaderboard.register()
class SetTrackedEmoji(
    lightbulb.SlashCommand,
    name="setemoji",
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

@leaderboard.register()
class ViewTrackedEmoji(
    lightbulb.SlashCommand,
    name="viewemoji",
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

@leaderboard.register()
class ViewLeaderboard(
    lightbulb.SlashCommand,
    name="view",
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

            for entry in emote_counts:
                if entry.get("guild_id") == str(ctx.guild_id) and entry.get("emoji_id") == tracked_emoji:
                    user_counts.append({
                        "user_id": member_doc["id"],
                        "username": member_doc.get("username", "Unknown"),
                        "count": entry["count"]
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
                f"{medal} <@{user_data['user_id']}> - {user_data['count']} reactions"
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

        embed = hikari.Embed(
            title=f"🏆 Your {emoji_display} Rank",
            description=f"You are ranked **#{rank}** out of **{total_users}** users for the emoji {emoji_display} with a total of **{user_count}** reactions!",
            color=0x3498DB
        )

        embed.set_footer(
            text="Use /leaderboard view to see the full leaderboard!"
        )

        await ctx.respond(embed=embed, ephemeral=True)


loader.command(leaderboard)