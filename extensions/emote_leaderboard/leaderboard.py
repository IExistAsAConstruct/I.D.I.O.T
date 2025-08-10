import os

import hikari
import lightbulb

loader = lightbulb.Loader()
leaderboard = lightbulb.Group("leaderboard", "Emote leaderboard group")

def get_emote_leaderboard_list() -> list[int]:
    """
    Retrieve a list of emoji IDs from the environment variable used in local emote leaderboards.

    Returns:
        list[int]: A list of admin role IDs.
    """
    roles = os.getenv("EMOTE_LEADERBOARD")
    if roles:
        return [int(role_id.strip()) for role_id in roles.split(",") if role_id.strip().isdigit()]
    return []

async def increment_emoji_count(guild_id: int, emoji_id: int) -> None:
    """
    Increment the count of an emoji in the database.

    Args:
        guild_id (int): The ID of the guild where the emoji was used.
        emoji_id (int): The ID of the emoji to increment.
    """
    # Here you would implement the logic to increment the emoji count in your database
    # For example, using a MongoDB collection or any other database you are using
    pass

emotes_in_leaderboard = get_emote_leaderboard_list()

# Emote counter
@loader.listener(hikari.GuildReactionAddEvent)
async def emote_counter(event: hikari.GuildReactionAddEvent) -> None:
    if event.member.is_bot:
        return

    try:
        if event.emoji_id:
            emoji = await event.app.rest.fetch_emoji(event.guild_id, event.emoji_id)
            print(emoji.guild_id, emoji.id, emoji.name)

        else:
            emoji = event.emoji_name
            print(emoji)

        if emoji.id in emotes_in_leaderboard or emoji.name in emotes_in_leaderboard:
            # Increment the emoji count in the database
            # Assuming you have a function to increment the emoji count
            await increment_emoji_count(event.guild_id, emoji.id or emoji.name)

    except hikari.NotFoundError:
        # If the emoji is not found, it might be a custom emoji that was deleted
        return