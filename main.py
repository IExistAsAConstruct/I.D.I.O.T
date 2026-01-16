#region Imports
import os
import uuid
import asyncio

from datetime import datetime, timezone, timedelta
from dotenv import main
import hikari
import lightbulb
from hikari import Intents
from database import members

import extensions
from hooks import fail_if_not_admin_or_owner
#endregion

#region Bot Setup

main.load_dotenv()

INTENTS = Intents.GUILD_MEMBERS | Intents.GUILDS | Intents.DM_MESSAGES | Intents.GUILD_MESSAGES | Intents.MESSAGE_CONTENT | Intents.GUILD_MESSAGE_REACTIONS

bot = hikari.GatewayBot(os.getenv("BOT_TOKEN"), intents=INTENTS)
client = lightbulb.client_from_app(bot)

bot.subscribe(hikari.StartingEvent, client.start)

registry = client.di.registry_for(lightbulb.di.Contexts.DEFAULT)

registry.register_factory(hikari.GatewayBot, lambda: bot)
registry.register_factory(lightbulb.GatewayEnabledClient, lambda: client)

#endregion

#region Starting Events

@bot.listen(hikari.StartingEvent)
async def on_startup(_: hikari.StartingEvent) -> None:
    print("Bot is starting...")
    print("Loading extensions...")
    await client.load_extensions_from_package(extensions, recursive=True)
    print("Extensions loaded successfully.")
    await client.start()

@bot.listen(hikari.StartedEvent)
async def on_started(_: hikari.StartedEvent) -> None:
    print("Bot has started successfully!")

#endregion

#region Commands - General

@client.register()
class Ping(
    lightbulb.SlashCommand,
    name = "ping",
    description = "Check the bot's latency."
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        latency = bot.heartbeat_latency * 1000
        await ctx.respond(f"Pong! Latency: {latency:.2f} ms")

@client.register()
class Announcement(
    lightbulb.SlashCommand,
    name = "announcement",
    description = "Send an announcement to a specific channel.",
    hooks = [fail_if_not_admin_or_owner]
):

    message = lightbulb.string("message", "Announcement message")
    channel = lightbulb.channel("channel", "Channel to send the announcement to")
    attachment = lightbulb.attachment("attachment", "Optional attachment for the announcement", default=None)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        channel = self.channel
        message = self.message

        embed = hikari.Embed(
            title="Announcement!",
            description=message,
            color=0x00FF00,  # Green color
            timestamp=datetime.now().astimezone()
        )

        try:
            await bot.rest.create_message(
                channel=channel.id,
                embed=embed
            )
            await ctx.respond(f"Announcement sent to {channel.mention}!", ephemeral= True)
        except Exception as e:
            await ctx.respond(f"Failed to send announcement: {str(e)}", ephemeral= True)

#endregion

#region Member Join and Message Events

@bot.listen(hikari.MessageCreateEvent)
async def on_message_create(event: hikari.MessageCreateEvent) -> None:
    member = event.author
    if not member:
        return

    # Check if the member already exists in the database
    existing_member = members.find_one({"id": str(member.id)})
    if existing_member:
        return

    # Create a new member document
    new_member = {
        "id": str(member.id),
        "username": member.username,
        "display_name": member.display_name,
        "cash": 1000,  # Default starting cash (cash name customizable)
        "bank": 0,  # Default starting bank balance
        "debts": [], # List of debts
        "total_debt": 0, # Total debt amount
        "credit_score": 500, # Credit score
        "wins": 0, # Wins in gambling
        "losses": 0, # Losses in gambling
        "trophies": [], # List of trophies
        "emote_count": [], # Count of certain emotes used
        "emote_rank": [],
        "joined_at": datetime.now(timezone.utc),
        "created_at": member.created_at
    }

    # Insert the new member into the database
    members.insert_one(new_member)
    print(f"New member added: {member.username} (ID: {member.id})")

@bot.listen(hikari.MemberCreateEvent)
async def on_member_create(event: hikari.MemberCreateEvent) -> None:
    member = event.member
    if not member:
        return

    # Check if the member already exists in the database
    existing_member = members.find_one({"id": member.id})
    if existing_member:
        return

    # Create a new member document
    new_member = {
        "id": str(member.id),
        "username": member.username,
        "display_name": member.display_name,
        "cash": 1000,  # Default starting cash (cash name customizable)
        "bank": 0,  # Default starting bank balance
        "debts": [], # List of debts
        "total_debt": 0, # Total debt amount
        "credit_score": 500, # Credit score
        "wins": 0, # Wins in gambling
        "losses": 0, # Losses in gambling
        "trophies": [], # List of trophies
        "emote_count": [], # Count of certain emotes used
        "emote_rank": [],
        "joined_at": datetime.now(timezone.utc),
        "created_at": member.created_at
    }

    # Insert the new member into the database
    members.insert_one(new_member)
    print(f"New member added: {member.username} (ID: {member.id})")

#endregion


class TestModal(lightbulb.components.Modal):
    def __init__(self) -> None:
        self.text = self.add_short_text_input("Enter text here")

    async def on_submit(self, ctx: lightbulb.components.ModalContext) -> None:
        await ctx.respond(f"You entered: {ctx.value_for(self.text)}", ephemeral=True)

@client.register()
class TestModalCommand(
    lightbulb.SlashCommand,
    name="testmodal",
    description="Test modal command"
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, client: lightbulb.Client) -> None:
        modal = TestModal()

        await ctx.respond_with_modal("test modal", c_id := str(uuid.uuid4()), components=modal)
        try:
            await modal.attach(client, c_id)
        except asyncio.TimeoutError:
            await ctx.respond("Modal timed out.", ephemeral=True)

bot.run()