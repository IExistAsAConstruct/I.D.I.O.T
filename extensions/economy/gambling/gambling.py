#region Imports
from datetime import datetime, timezone, timedelta
import asyncio
import random
from typing import Any

import hikari
import lightbulb
from attr import dataclass

from database import members, transactions
from hooks import fail_if_not_admin_or_owner
import extensions.economy.gambling.gamble_util as gu
import extensions.economy.economy_util as eu
from anydeck import AnyDeck, anydeck

#endregion

loader = lightbulb.Loader()
gambling = lightbulb.Group("gambling", "Gambling related commands and features.")
slots = gambling.subgroup("slots", "Slot machine commands.")
racing = gambling.subgroup("racing", "Horse racing commands.")
blackjack = gambling.subgroup("blackjack", "Blackjack commands.")

#region Slots

# Define slot symbols with their display characters, values, and weights
SLOT_SYMBOLS = {
    "🍒": {"value": 1, "weight": 35},  # Very common
    "🍊": {"value": 2, "weight": 30},  # Common
    "🍋": {"value": 3, "weight": 18},  # Uncommon
    "🍇": {"value": 5, "weight": 12},  # Uncommon
    "🍉": {"value": 10, "weight": 4},  # Rare
    "💎": {"value": 25, "weight": 1},  # Very rare
}

# Create weighted symbol list for random selection
WEIGHTED_SYMBOLS = []
for symbol, data in SLOT_SYMBOLS.items():
    WEIGHTED_SYMBOLS.extend([symbol] * data["weight"])


def get_biased_reel_result(previous_results=None):
    """
    Get a result for a slot reel with bias against matching previous results.
    This creates a subtle house edge by making matches less likely.

    Args:
        previous_results: List of symbols already shown in previous reels

    Returns:
        A symbol chosen with weighted probability but biased against matches
    """
    if not previous_results:
        # For the first reel, just use normal weighted random
        return random.choice(WEIGHTED_SYMBOLS)

    roll = random.random()

    if len(previous_results) == 1:
        if roll < 0.10:
            non_matching = [s for s in SLOT_SYMBOLS.keys() if s != previous_results[0]]
            return random.choice(non_matching)
    elif len(previous_results) == 2:
        if roll < 0.20:
            if previous_results[0] == previous_results[1]:
                if random.random() < 0.80:
                    non_matching = [s for s in SLOT_SYMBOLS.keys() if s != previous_results[0]]
                    return random.choice(non_matching)
            else:
                non_matching = [s for s in SLOT_SYMBOLS.keys()
                                if s != previous_results[0] and s != previous_results[1]]
                if non_matching:
                    return random.choice(non_matching)

    choices = []
    for symbol, data in SLOT_SYMBOLS.items():
        is_match = symbol in previous_results

        weight = data["weight"] * (0.4 if is_match else 1.0)

        choices.extend([symbol] * int(weight))

    return random.choice(choices) if choices else random.choice(WEIGHTED_SYMBOLS)

@slots.register()
class SlotMachine(
    lightbulb.SlashCommand,
    name="spin",
    description="Play the slot machine."
):
    bet = lightbulb.number("bet", "Amount of cash to bet. Min bet is 10, max bet is 1000.", min_value=10, max_value=1000)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:

        can_bet, reason = gu.validate_bet(str(ctx.member.id), self.bet)

        if not can_bet:
            await ctx.respond(f"❌ You cannot place that bet: {reason}")
            return

        msg = await ctx.respond("🎰 Spinning the slots...")

        spinning_symbols = list(SLOT_SYMBOLS.keys())

        final_slots = ["", "", ""]

        for _ in range(5):
            # Generate random symbols for the spinning effect
            spin = [random.choice(spinning_symbols) for _ in range(3)]
            await ctx.edit_response(msg, f"🎰 | {spin[0]} | {spin[1]} | {spin[2]} |")
            await asyncio.sleep(0.2)

        final_slots[0] = get_biased_reel_result()# Determine first reel result
        for _ in range(5):
            spin = [final_slots[0], random.choice(spinning_symbols), random.choice(spinning_symbols)]
            await ctx.edit_response(msg, f"🎰 | {spin[0]} | {spin[1]} | {spin[2]} |")
            await asyncio.sleep(0.2)

        final_slots[1] = get_biased_reel_result([final_slots[0]])  # Determine second reel result
        for _ in range(5):
            spin = [final_slots[0], final_slots[1], random.choice(spinning_symbols)]
            await ctx.edit_response(msg, f"🎰 | {spin[0]} | {spin[1]} | {spin[2]} |")
            await asyncio.sleep(0.3)

        final_slots[2] = get_biased_reel_result([final_slots[0], final_slots[1]])  # Determine third reel result
        slot_display = f"🎰 | {final_slots[0]} | {final_slots[1]} | {final_slots[2]} |"
        await ctx.edit_response(msg, slot_display)

        # Determine if user won and calculate prize
        result_message = ""
        payout = 0
        profit = 0

        if final_slots[0] == final_slots[1] == final_slots[2]:
            # Jackpot - all three symbols match
            symbol_value = SLOT_SYMBOLS[final_slots[0]]["value"]
            prize_multiplier = 5
            payout = self.bet * symbol_value * prize_multiplier
            profit = payout - self.bet
            result_message = f"🎉 **JACKPOT!** 🎉\nYou got three {final_slots[0]} symbols!\nPrize: ${payout:.2f} (Net profit: {profit:.2f})!"

        elif final_slots[0] == final_slots[1] or final_slots[1] == final_slots[2] or final_slots[0] == final_slots[2]:
            # Two matching symbols
            if final_slots[0] == final_slots[1]:
                matching_symbol = final_slots[0]
            elif final_slots[1] == final_slots[2]:
                matching_symbol = final_slots[1]
            else:
                matching_symbol = final_slots[0]

            symbol_value = SLOT_SYMBOLS[matching_symbol]["value"]
            prize_multiplier = 1.5
            payout = self.bet * symbol_value * prize_multiplier
            profit = payout - self.bet
            result_message = f"🎊 **WIN!** 🎊\nYou matched two {matching_symbol} symbols!\nPrize: ${payout:.2f} (Net profit: {profit:.2f})!"

        else:
            # No matches
            result_message = "😢 **Better luck next time!**\nNo matching symbols found."

        # Add payout to user's account if they won
        gu.process_gambling_result(
            user_id=str(ctx.member.id),
            guild_id=str(ctx.guild_id),
            game_type="slots",
            bet_amount=self.bet,
            payout_amount=payout,
            result="win" if payout > 0 else "loss",
            game_data={"symbols": final_slots}
        )

        # Show the final result with the prize message
        final_message = f"{slot_display}\n\n{result_message}"
        await ctx.edit_response(msg, final_message)


@slots.register()
class SlotsHelp(
    lightbulb.SlashCommand,
    name="help",
    description="Get help with playing the slot machine."
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        embed = hikari.Embed(
            title="🎰 Slot Machine Help",
            color=0x2B2D31,
            description="Try your luck with the slot machine! Bet cash and win prizes based on matching symbols."
        )

        embed.add_field(
            name="How to Play",
            value="Use `/slots bet:[amount]` to place a bet between 10 and 1000 dollars.",
            inline=False
        )

        embed.add_field(
            name="Winning Combinations",
            value="• Three matching symbols: JACKPOT! Win 5× your bet multiplied by symbol value.\n"
                  "• Two matching symbols: Win 1.5× your bet multiplied by symbol value.\n"
                  "• No matches: You lose your bet.",
            inline=False
        )
        embed.add_field(
            name="Symbol Values",
            value="🍒 Cherry: 1× multiplier (common)\n"
                  "🍊 Orange: 2× multiplier (common)\n"
                  "🍋 Lemon: 3× multiplier (uncommon)\n"
                  "🍇 Grapes: 5× multiplier (uncommon)\n"
                  "🍉 Watermelon: 10× multiplier (rare)\n"
                  "💎 Diamond: 25× multiplier (very rare)",
            inline=False
        )

        await ctx.respond(embed=embed)
#endregion

#region Horse Racing

#region Variables and Data Classes
active_races = {}
pending_bets = {}

HORSE_NAMES = [
    "Lightning Hooves", "Skibidi Rizz", "Debt Collector", "Who", "What", "I Don't Know",
    "Forrest Gump", "Horse Girl", "Birthday Suit", "Gallop", "Lucky Day", "Loser",
    "Crash and Burn", "Special Delivery", "Happy Hour", "Dash", "Prancer",
    "Sagittarius"
]

BETTING_DURATION = 60
HOUSE_RAKE = 0.10
MIN_BETTORS = 2
RACE_DISTANCE = 100

@dataclass
class Horse:
    number: int
    name: str
    position: float = 0.0
    speed: int = 0
    stamina: int = 0
    finished: bool = False

    def __attrs_post_init__(self):
        self.speed = random.randint(5, 10)
        self.stamina = random.randint(3, 10)

    def get_odds_indicator(self) -> str:
        avg = (self.speed + self.stamina) / 2
        if avg >= 9: return "⭐⭐⭐⭐⭐ (Favorite)"
        if avg >= 7.5: return "⭐⭐⭐⭐ (Strong)"
        if avg >= 6: return "⭐⭐⭐ (Average)"
        if avg >= 4.5: return "⭐⭐ (Underdog)"
        return "⭐ (Long Shot)"

@dataclass
class Bet:
    user_id: str
    username: str
    amount: float
    bet_type: str # Win, Place, Show, Exacta, Trifecta, Superfecta
    horses: list[int]
#endregion

#region RaceSession

def get_unique_horses() -> list[Horse]:
    """Get a random set of 8 horses, ensuring unique names."""
    horses = random.sample(HORSE_NAMES, 8)
    unique_horses = [Horse(i + 1, name) for i, name in enumerate(horses)]
    # DEBUG: checks each horse's speed and stamina
    print(
        "\n".join([
            f"Horse #{h.number} - {h.name}: Speed={h.speed}, Stamina={h.stamina}"
            for h in unique_horses
        ])
    )
    return unique_horses

class RaceSession:
    def __init__(self, guild_id: int, channel_id: int):
        self.race_id = eu.generate_short_id()
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.thread_id = None
        self.status = "betting"
        self.horses = get_unique_horses()
        self.bets = {}
        self.total_pool = 0.0
        self.created_at = datetime.now(timezone.utc)
        self.betting_end_time = self.created_at + timedelta(seconds=BETTING_DURATION)
        self.message_id = None
        self.winner = None
        self.podium = []

    def add_bet(self, user_id: str, username: str, bet_type: str, horse_list: list[int], amount: float) -> tuple[bool, str]:
        """Add a bet. Bets are locked once placed. Returns (success, message)."""
        if self.status != "betting":
            return False, "Betting is closed for this race."

        if user_id in self.bets:
            return False, f"You already bet ${self.bets[user_id].amount:.2f} on horse #{self.bets[user_id].horse_number}. No changes allowed!"

        can_bet, error = gu.validate_bet(user_id, amount)
        if not can_bet:
            return False, f"Cannot place bet: {error}"


        horse_objs = [horse for horse in self.horses if horse.number in horse_list]
        bet_on_text = ", ".join([f"#{h.number} ({h.name})" for h in horse_objs])

        gu.deduct_bet(user_id, amount, f"Bet on Horses {bet_on_text}", "horse_racing")

        self.bets[user_id] = Bet(user_id, username, amount, bet_type, horse_list)
        self.total_pool += amount

        if len(horse_list) == 1:
            horse_number = horse_list[0]
            return True, f"✅ Bet placed: ${amount:.2f} on horse #{horse_number} ({self.horses[horse_number-1].name})."

        return True, f"✅ Bet placed: ${amount:.2f} on horses {bet_on_text}."

    def get_bet_summary(self) -> str:
        """Get a summary of all bets placed."""
        if not self.bets:
            return "No bets placed yet! Be the first to bet!"

        horse_bets = {i: 0 for i in range(1, 9)}
        horse_totals = {i: 0.0 for i in range(1, 9)}

        for bet in self.bets.values():
            first_horse = bet.horses[0]
            horse_bets[first_horse] += 1
            horse_totals[first_horse] += bet.amount

        lines = [f"**Total Pool: ${self.total_pool:.2f}** | **Bettors: {len(self.bets)}**\n"]
        for i, horse in enumerate(self.horses, 1):
            count = horse_bets[i]
            total = horse_totals[i]
            if count > 0:
                lines.append(f"🐴 #{i} **{horse.name}**: {count} bet(s) totaling ${total:.2f}")
            else:
                lines.append(f"🐴 #{i} **{horse.name}**: No bets yet")

        return "\n".join(lines)

    def calculate_payouts(self, finished_order: list[Horse]) -> dict[str, float]:
        """Calculate pari-mutuel payouts for winning bets."""
        payouts = {}

        podium = [h.number for h in finished_order[:4]]  # Top 4 horses

        self.podium = [h for h in finished_order[:4]]

        for user_id, bet in self.bets.items():
            win_amount = 0.0

            if bet.bet_type in ["win", "place", "show"]:
                horse_num = bet.horses[0]
                horse_obj = next((h for h in self.horses if h.number == horse_num), None)
                base_mult = self._get_multiplier(horse_obj)

                if bet.bet_type == "win" and podium[0] == horse_num:
                    win_amount = bet.amount * base_mult

                elif bet.bet_type == "place" and horse_num in podium[:2]:
                    win_amount = bet.amount * (base_mult * 0.6)

                elif bet.bet_type == "show" and horse_num in podium[:3]:
                    win_amount = bet.amount * (base_mult * 0.3)

            elif bet.bet_type == "exacta" and podium[:2] == bet.horses:
                win_amount = bet.amount * 15

            elif bet.bet_type == "trifecta" and podium[:3] == bet.horses:
                win_amount = bet.amount * 75

            elif bet.bet_type == "superfecta" and podium[:4] == bet.horses:
                win_amount = bet.amount * 200

            if win_amount > 0:
                payouts[user_id] = win_amount

        return payouts

    def _get_multiplier(self, horse: Horse) -> float:
        """Get base multiplier based on horse odds."""
        avg = (horse.speed + horse.stamina) / 2
        if avg >= 9: return 1.25 # Favorite
        if avg >= 7.5: return 2.5 # Strong
        if avg >= 6: return 5 # Average
        if avg >= 4.5: return 15 # Underdog
        return 50.0 # Long Shot
#endregion

#region Modal
class BetModal(lightbulb.components.Modal):
    def __init__(self, race_session: RaceSession) -> None:
        self.race_session = race_session

        self.bet_amount = self.add_short_text_input(
            custom_id="bet_amount",
            label="Bet Amount (min $10)",
            placeholder="Enter the amount you want to bet",
            required=True,
            min_length=2,
            max_length=10
        )

    async def on_submit(self, ctx: lightbulb.components.ModalContext) -> None:
        """Handle bet submission."""
        try:
            bet_amount = int(ctx.value_for(self.bet_amount))
        except ValueError:
            await ctx.respond("❌ Invalid input. amount must be a number.", ephemeral=True)
            return

        if bet_amount < 10:
            await ctx.respond("❌ Minimum bet amount is $10.", ephemeral=True)
            return

        pending = pending_bets.get(ctx.user.id)
        if not pending:
            await ctx.respond("❌ No pending bet found. Please start again.", ephemeral=True)
            return

        success, message = self.race_session.add_bet(
            str(ctx.user.id),
            ctx.user.username,
            pending["bet_type"],
            pending["horses"],
            bet_amount
        )

        if success:
            del pending_bets[ctx.user.id]

        await ctx.respond(message, ephemeral=True)
#endregion

#region Racing Menus
class HorseRaceMenu(lightbulb.components.Menu):
    def __init__(self, client: lightbulb.Client) -> None:
        self.client = client
        self.btn = self.add_interactive_button(
            hikari.ButtonStyle.PRIMARY,
            self.on_button_press,
            label="🎰 Place Your Bet!"
        )

    async def on_button_press(self, ctx: lightbulb.components.MenuContext) -> None:
        guild_id = ctx.guild_id
        race_session = active_races.get(guild_id)

        if not race_session:
            await ctx.interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                "This race is no longer active.",
                flags=hikari.MessageFlag.EPHEMERAL
            )
            return

        if race_session.status != "betting":
            await ctx.interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                "Betting is closed for this race.",
                flags=hikari.MessageFlag.EPHEMERAL
            )
            return

        pending_bets[ctx.user.id] = {
            "race_id": race_session.race_id,
            "bet_type": None,
            "horses": [],
            "timestamp": datetime.now(timezone.utc)
        }

        select_bet = BetTypeMenu(self.client, race_session)

        await ctx.respond(
        "Select your bet type:",
        components=select_bet,
        flags=hikari.MessageFlag.EPHEMERAL
        )
        try:
            await select_bet.attach(self.client)
        except (asyncio.TimeoutError, TimeoutError):
            pass


class BetTypeMenu(lightbulb.components.Menu):
    def __init__(self, client: lightbulb.Client, race_session: RaceSession) -> None:
        self.client = client
        self.race_session = race_session

        options = [
            lightbulb.components.TextSelectOption(label="Win", value="win", description="Bet on a horse to finish first.", emoji="🏆"),
            lightbulb.components.TextSelectOption(label="Place", value="place", description="Bet on a horse to finish first or second.", emoji="🥈"),
            lightbulb.components.TextSelectOption(label="Show", value="show", description="Bet on a horse to finish first, second, or third.", emoji="🥉"),
            lightbulb.components.TextSelectOption(label="Exacta", value="exacta", description="Bet on the first two horses in exact order.", emoji="🎯"),
            lightbulb.components.TextSelectOption(label="Trifecta", value="trifecta", description="Bet on the first three horses in exact order.", emoji="🎲"),
            lightbulb.components.TextSelectOption(label="Superfecta", value="superfecta", description="Bet on the first four horses in exact order.", emoji="🎰")
        ]

        self.select = self.add_text_select(
            options=options,
            on_select=self.on_bet_type_selected,
            placeholder="Select Bet Type...",
            min_values=1,
            max_values=1
        )

    async def on_bet_type_selected(self, ctx: lightbulb.components.MenuContext) -> None:
        bet_selected = ctx.selected_values_for(self.select)[0]

        pending = pending_bets.get(ctx.user.id)
        if pending["bet_type"]:
            await ctx.respond("You have already selected a bet type.", flags=hikari.MessageFlag.EPHEMERAL)
            return

        pending["bet_type"] = bet_selected

        if bet_selected == "win" or bet_selected == "place" or bet_selected == "show":
            num_horses = 1
            label_text = "Select Your Horse!"
        elif bet_selected == "exacta":
            num_horses = 2
            label_text = "Select Your 1st Horse!"
        elif bet_selected == "trifecta":
            num_horses = 3
            label_text = "Select Your 1st Horse!"
        else:  # superfecta
            num_horses = 4
            label_text = "Select Your 1st Horse!"

        horse_selection = HorseSelectionMenu(
            self.client,
            self.race_session,
            label_text,
            []
        )

        await ctx.respond(
            label_text,
            components=horse_selection,
            flags=hikari.MessageFlag.EPHEMERAL
        )

        try:
            await horse_selection.attach(self.client)
        except (asyncio.TimeoutError, TimeoutError):
            pass

class HorseSelectionMenu(lightbulb.components.Menu):
    def __init__(self, client: lightbulb.Client, race_session: RaceSession, position_label: str, selected_horses: list[int]) -> None:
        self.client = client
        self.race_session = race_session
        self.position_label = position_label
        self.selected_horses = selected_horses

        choices = []

        for horse in race_session.horses:
            if horse.number not in selected_horses:
                choices.append(
                    lightbulb.components.TextSelectOption(
                        label=f"#{horse.number} - {horse.name}",
                        value=str(horse.number),
                        description=horse.get_odds_indicator(),
                        emoji="🐴"
                    )
                )

        self.select = self.add_text_select(
            options=choices,
            on_select=self.on_horse_selected,
            placeholder=self.position_label,
            min_values=1,
            max_values=1
        )

    async def on_horse_selected(self, ctx: lightbulb.components.MenuContext):
        horse_selected = int(ctx.selected_values_for(self.select)[0])
        self.selected_horses.append(horse_selected)

        pending = pending_bets.get(ctx.user.id)
        pending["horses"].append(horse_selected)

        bet_type = pending["bet_type"]
        horses_so_far = len(pending["horses"])

        required_horses = {
            "win": 1, "place": 1, "show": 1,
            "exacta": 2, "trifecta": 3, "superfecta": 4
        }

        if horses_so_far < required_horses[bet_type]:
            position_labels = ["1st", "2nd", "3rd", "4th"]
            next_label = f"Select Your {position_labels[horses_so_far]} Horse!"

            next_menu = HorseSelectionMenu(
                self.client,
                self.race_session,
                next_label,
                pending["horses"]
            )

            await ctx.respond(
                next_label,
                components=next_menu,
                flags=hikari.MessageFlag.EPHEMERAL
            )
            try:
                await next_menu.attach(self.client)
            except (asyncio.TimeoutError, TimeoutError):
                pass
        else:
            modal = BetModal(self.race_session)
            await ctx.respond_with_modal("Place Your Bet", c_id := eu.generate_short_id(), components=modal)
            try:
                await modal.attach(self.client, c_id)
            except (asyncio.TimeoutError, TimeoutError):
                pass

#endregion

#region Running The Race

async def run_race(client: lightbulb.Client, message: hikari.Message, race_session: RaceSession) -> None:
    """Simulate and animate the race."""
    race_session.status = "racing"
    thread = await client.rest.create_message_thread(
        race_session.channel_id,
        message.id,  # Links the thread to the betting msg
        f"🏇 Race {race_session.race_id[:8]} - Live!"
    )
    race_session.thread_id = thread.id

    track_msg = await client.rest.create_message(thread.id, "🏁 **The gates are open!**")

    finished_order = []

    while len(finished_order) < 8:
        for horse in race_session.horses:
            if not horse.finished:
                surge = random.uniform(0, horse.stamina / 2)
                advance = random.uniform(2, horse.speed) + surge
                horse.position += advance

                if horse.position >= RACE_DISTANCE:
                    horse.position = RACE_DISTANCE
                    horse.finished = True
                    if horse not in finished_order:
                        finished_order.append(horse)

        track_lines = ["🏁 ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬ 🏁"]


        sorted_horses = sorted(race_session.horses, key=lambda h: h.number)

        for horse in sorted_horses:
            progress = int((horse.position / RACE_DISTANCE) * 15)
            lane = ["—"] * 15

            if not horse.finished:
                lane[min(progress, 14)] = "🏇"
            else:
                lane[-1] = "🏆"

            track_lines.append(f"`#{horse.number}` {''.join(lane)} | **{horse.name}**")

        track_lines.append("🏁 ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬ 🏁")

        await client.rest.edit_message(
            thread.id,
            track_msg.id,
            content="\n".join(track_lines)
        )
        await asyncio.sleep(1.5)

    race_session.status = "finished"
    race_session.winner = finished_order[0]

    payouts = race_session.calculate_payouts(finished_order)

    for user_id, payout_amount in payouts.items():
        bet = race_session.bets[user_id]
        gu.process_racing_payout(
            user_id,
            str(race_session.guild_id),
            payout_amount,
            "win",
            bet.amount,
            "racing",
            {
                "race_id": race_session.race_id,
                "horse_numbers": bet.horses,
                "horse_names": [h.name for h in race_session.podium if h.number in bet.horses],
                "total_pool": race_session.total_pool
            }
        )

    for user_id, bet in race_session.bets.items():
        if user_id not in payouts:
            gu.process_racing_payout(
                user_id=user_id,
                guild_id=str(race_session.guild_id),
                payment_amount=0,
                result="loss",
                bet_amount=bet.amount,
                game_type="racing",
                game_data={
                    "race_id": race_session.race_id,
                    "horse_number": bet.horses[0],
                    "total_pool": race_session.total_pool
                }
            )

    results_embed = hikari.Embed(
        title="🏆 Race Results",
        description=f"**Winner: Horse #{race_session.winner.number} - {race_session.winner.name}**",
        color=0xFFD700
    )

    results_embed.add_field(
        name="Final Standings",
        value="\n".join([
            f"{'🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else f'{i + 1}.'} Horse #{h.number} - {h.name}"
            for i, h in enumerate(finished_order)
        ]),
        inline=False
    )

    if payouts:
        payout_lines = []
        for user_id, payout in payouts.items():
            bet = race_session.bets[user_id]
            profit = payout - bet.amount
            payout_lines.append(f"<@{user_id}>: Bet ${bet.amount:.2f} → Won ${payout:.2f} (Profit: +${profit:.2f})")

        results_embed.add_field(
            name="💰 Winners",
            value="\n".join(payout_lines),
            inline=False
        )
    else:
        results_embed.add_field(
            name="💰 Winners",
            value="No one bet on the winning horse! House takes all.",
            inline=False
        )

    house_take = race_session.total_pool * HOUSE_RAKE
    results_embed.set_footer(text=f"Total Pool: ${race_session.total_pool:.2f} | House Take: ${house_take:.2f}")

    await client.rest.create_message(thread.id, embed=results_embed)
    await client.rest.create_message(race_session.channel_id, embed=results_embed)

    # Clean up
    del active_races[race_session.guild_id]

async def countdown_and_race(client: lightbulb.Client, channel: int, race_session: RaceSession, message: hikari.Message) -> None:
    """Handle countdown and start race"""
    # Wait for betting period
    await asyncio.sleep(BETTING_DURATION)

    # Check minimum bettors
    if len(race_session.bets) < MIN_BETTORS:
        # Refund all bets
        for bet in race_session.bets.values():
            members.update_one(
                {"id": bet.user_id},
                {"$inc": {"cash": bet.amount}}
            )

        embed = hikari.Embed(
            title="❌ Race Cancelled",
            description=f"Not enough bettors (need {MIN_BETTORS}, got {len(race_session.bets)}).\n"
                        "All bets have been refunded.",
            color=0xFF0000
        )

        await client.rest.edit_message(
            channel=race_session.channel_id,
            message=message,
            embed=embed,
            components=[]
        )

        del active_races[race_session.guild_id]
        return

    # Update message - betting closed
    embed = hikari.Embed(
        title="🏁 Betting Closed!",
        description=f"The race is about to begin!\n\n{race_session.get_bet_summary()}",
        color=0xFFD700
    )

    await client.rest.edit_message(
        channel=race_session.channel_id,
        message=message,
        embed=embed,
        components=[]
    )

    # Start race
    await run_race(client, message, race_session)

#endregion

#region Commands - Racing

@racing.register()
class RaceStart(
    lightbulb.SlashCommand,
    name="start",
    description="Start a new horse race! 60 seconds to place your bets."
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, client: lightbulb.Client) -> None:
        """Start a new race"""
        guild_id = ctx.guild_id

        # Check if race already active
        if guild_id in active_races:
            await ctx.respond("❌ A race is already in progress in this server!", ephemeral=True)
            return

        # Create new race
        race_session = RaceSession(guild_id, ctx.channel_id)
        active_races[guild_id] = race_session

        # Create embed
        embed = hikari.Embed(
            title="🏇 Horse Race Starting!",
            description=f"**Race ID:** {race_session.race_id[:8]}\n\n"
                        f"Click the button below to place your bet!\n"
                        f"**Betting closes in {BETTING_DURATION} seconds.**",
            color=0x00FF00,
            timestamp=race_session.betting_end_time
        )

        # List horses
        horse_list = "\n".join([
            f"#{h.number} **{h.name}** | Form: {h.get_odds_indicator()}"
            for h in race_session.horses
        ])
        embed.add_field(name="🐴 Horses & Odds", value=horse_list, inline=False)

        embed.set_footer(text=f"Minimum bet: $10 | House take: {HOUSE_RAKE * 100:.0f}%")
        # Create join button

        menu = HorseRaceMenu(client)

        resp = await client.rest.create_message(
            ctx.channel_id,
            "It's time to bet!",
            embed=embed,
            components=menu
        )

        try:
            await menu.attach(client, timeout=BETTING_DURATION)
        except(asyncio.TimeoutError, TimeoutError):
            pass

        # Start countdown
        asyncio.create_task(countdown_and_race(client, ctx.channel_id, race_session, resp))

@racing.register()
class RaceHelp(
    lightbulb.SlashCommand,
    name="help",
    description="Get help with horse racing."
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        help_description = ("Horse racing is a betting game where you can wager cash on virtual horses.\n\n"
                            f"Use the command /gambling racing start to start a race. Only one race can be "
                            f"active per server. You will have {BETTING_DURATION} seconds to place your bets.\n\n"
                            "You can bet on horses to Win, Place, Show, or make Exacta, Trifecta, or Superfecta bets.\n\n"
                            "**Bet Types:**\n"
                            "• Win: Bet on a horse to finish first. Bet multiplier is normal horse multiplier.\n"
                            "• Place: Bet on a horse to finish first or second. Bet multiplier is 60% of horse multiplier.\n"
                            "• Show: Bet on a horse to finish first, second, or third. Bet multiplier is 30% of horse multiplier.\n"
                            "• Exacta: Bet on the first two horses in exact order. Fixed 15× multiplier.\n"
                            "• Trifecta: Bet on the first three horses in exact order. Fixed 75× multiplier.\n"
                            "• Superfecta: Bet on the first four horses in exact order. Fixed 200× multiplier.\n\n"
                            "**Horse Stats:**\n"
                            "Each horse has Speed and Stamina stats that affect their performance.\n"
                            "Horses with higher stats have better odds of winning but lower payout multipliers.\n\n"
                            "**Horse Multipliers:**\n"
                            "• ⭐⭐⭐⭐⭐ (Favorite): 1.25×\n"
                            "• ⭐⭐⭐⭐ (Strong): 2.5×\n"
                            "• ⭐⭐⭐ (Average): 5×\n"
                            "• ⭐⭐ (Underdog): 15×\n"
                            "• ⭐ (Long Shot): 50×\n\n"
                            "Good luck and may the best horse win!")

        help_embed = hikari.Embed(
            title="🏇 Horse Racing Help",
            description=help_description,
            color=0x2B2D31,
            timestamp=datetime.now(timezone.utc)
        )

        await ctx.respond(embed=help_embed)

#endregion

#endregion

#region Blackjack

#region Variables

CARD_VALUES = {
    "Ace": 11,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "10": 10,
    "Jack": 10,
    "Queen": 10,
    "King": 10
}

OUTCOME_PAYOUTS = {
    "blackjack": 2.5,  # 3:2 payout for blackjack
    "win": 2.0,        # 1:1 payout for regular win
    "push": 1.0,       # Return original bet
    "surrender": 0.5,  # Return half the bet
    "loss": 0.0        # Lose entire bet
}

#endregion

#region Hand Class

class Hand:
    """Represents a blackjack hand with cards and methods to evaluate its value."""

    def __init__(self, cards: list[anydeck.Card] = None):
        """Initialize a hand with optional starting cards."""
        self.cards = cards or []

    def add_card(self, card: anydeck.Card) -> None:
        """Add a card to the hand."""
        self.cards.append(card)

    @property
    def value(self) -> int:
        """Calculate the total value of the hand, accounting for Aces."""
        total = sum(card.value for card in self.cards)
        ace_count = sum(1 for card in self.cards if card.face == 'Ace')

        # Adjust aces from 11 to 1 as needed to avoid busting
        while total > 21 and ace_count > 0:
            total -= 10
            ace_count -= 1

        return total

    @property
    def is_blackjack(self) -> bool:
        """Check if the hand is a natural blackjack (21 with exactly 2 cards)."""
        return len(self.cards) == 2 and self.value == 21

    @property
    def is_busted(self) -> bool:
        """Check if the hand is busted (over 21)."""
        return self.value > 21

    @property
    def can_split(self) -> bool:
        """Check if the hand can be split (2 cards of same value)."""
        return (len(self.cards) == 2 and
                self.cards[0].value == self.cards[1].value)

    def to_string(self, hide_second_card: bool = False) -> str:
        """
        Convert the hand to a string representation.

        Args:
            hide_second_card: If True, the second card will be hidden (for dealer's initial hand)
        """
        if not self.cards:
            return "Empty hand"

        if hide_second_card and len(self.cards) > 1:
            visible_card = f"{self.cards[0].suit}{self.cards[0].face}"
            return f"{visible_card} 🂠"

        return " ".join(f"{card.suit}{card.face}" for card in self.cards)

#endregion

#region Blackjack Game

class BlackjackGame:
    """Main class for managing a blackjack game session."""

    def __init__(self, player_id: int, bet_amount: int, message_id = hikari.Snowflakeish):
        """
        Initialize a new blackjack game.

        Args:
            player_id: The ID of the player
            bet_amount: The amount of cash bet on the game
        """
        self.player_id = player_id
        self.initial_bet = bet_amount
        self.message_id = message_id

        # Initialize game state
        self.deck = self._create_deck()
        self.main_hand = Hand()
        self.split_hand = None  # Will be set if player splits
        self.dealer_hand = Hand()
        self.current_hand = self.main_hand  # Reference to the active hand

        # Bet tracking
        self.main_bet = bet_amount
        self.split_bet = 0
        self.insurance_bet = 0

        # Game state flags
        self.active_hand_index = 0  # 0 for main hand, 1 for split hand
        self.is_complete = False
        self.has_surrendered = False
        self.insurance_available = False
        self.insurance_resolved = False

        # Deal initial cards
        self._deal_initial_cards()

    def _create_deck(self) -> AnyDeck:
        """Create and shuffle a standard 52-card deck with blackjack values."""
        deck = AnyDeck(
            shuffled=True,
            suits=('♣', '♦', '♥', '♠'),
            cards=('Ace', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'Jack', 'Queen', 'King')
        )
        deck.dict_to_value(CARD_VALUES)
        return deck

    def _deal_initial_cards(self) -> None:
        """Deal the initial two cards to player and dealer."""
        for _ in range(2):
            self.main_hand.add_card(self.deck.draw())
            self.dealer_hand.add_card(self.deck.draw())

        # Check if insurance is available (dealer's up-card is an Ace)
        self.insurance_available = self.dealer_hand.cards[0].face == 'Ace'

        # Check for immediate game end conditions (player or dealer blackjack)
        self._check_initial_blackjacks()

    def _check_initial_blackjacks(self) -> None:
        """Check for blackjack in the initial deal and update game state accordingly."""
        player_blackjack = self.main_hand.is_blackjack
        dealer_blackjack = self.dealer_hand.is_blackjack

        if player_blackjack or dealer_blackjack:
            self.is_complete = True

    def hit(self) -> anydeck.Card:
        """
        Add a card to the current hand.

        Returns:
            The card that was drawn.
        """
        card = self.deck.draw()
        self.current_hand.add_card(card)

        # Check if the hand is busted
        if self.current_hand.is_busted:
            # If this is the first hand in a split, move to the second hand
            if self.split_hand and self.active_hand_index == 0:
                self.switch_to_split_hand()
            else:
                # Game is complete if main hand busts or both hands bust
                self.is_complete = True

        return card

    def stand(self) -> None:
        """Stand on the current hand, potentially switching to split hand or ending the game."""
        # If this is the first hand in a split, move to the second hand
        if self.split_hand and self.active_hand_index == 0:
            self.switch_to_split_hand()
        else:
            # Player's turn is over, resolve dealer's hand
            self._play_dealer_hand()
            self.is_complete = True

    def double_down(self) -> anydeck.Card:
        """
        Double the bet on the current hand and draw exactly one card.

        Returns:
            The card that was drawn.
        """
        # Double the appropriate bet
        if self.active_hand_index == 0:
            self.main_bet *= 2
        else:
            self.split_bet *= 2

        # Draw one card
        card = self.hit()

        # If the hand didn't bust, stand automatically
        if not self.current_hand.is_busted:
            self.stand()

        return card

    def split(self) -> bool:
        """
        Split the player's hand into two separate hands.

        Returns:
            True if the split was successful, False otherwise.
        """
        # Check if split is possible
        if not self.main_hand.can_split or self.split_hand is not None:
            return False

        # Create the split hand with the second card from the main hand
        self.split_hand = Hand([self.main_hand.cards.pop()])

        # Add a new card to each hand
        self.main_hand.add_card(self.deck.draw())
        self.split_hand.add_card(self.deck.draw())

        # Set the split bet equal to the main bet
        self.split_bet = self.main_bet

        # Ensure current hand is still the main hand
        self.current_hand = self.main_hand
        self.active_hand_index = 0

        return True

    def surrender(self) -> bool:
        """
        Surrender the hand, recovering half the bet.

        Returns:
            True if surrender was successful, False if not allowed.
        """
        # Can only surrender on initial hand
        if len(self.main_hand.cards) > 2 or self.split_hand is not None:
            return False

        self.has_surrendered = True
        self.is_complete = True
        return True

    def take_insurance(self) -> bool:
        """
        Take insurance against dealer blackjack.

        Returns:
            True if insurance was successful, False if not available.
        """
        if not self.insurance_available or self.insurance_resolved:
            return False

        # Insurance bet is half the original bet
        self.insurance_bet = self.main_bet // 2

        # If dealer has blackjack, resolve insurance immediately
        if self.dealer_hand.is_blackjack:
            self.insurance_resolved = True
            self.is_complete = True

        return True

    def switch_to_split_hand(self) -> None:
        """Switch the active hand to the split hand."""
        if self.split_hand:
            self.current_hand = self.split_hand
            self.active_hand_index = 1

    def _play_dealer_hand(self) -> None:
        """Play the dealer's hand according to standard rules (hit on 16, stand on 17)."""
        # Dealer only plays if player hasn't busted all hands
        if (self.main_hand.is_busted and
                (self.split_hand is None or self.split_hand.is_busted)):
            return

        # Dealer hits until reaching at least 17
        while self.dealer_hand.value < 17:
            self.dealer_hand.add_card(self.deck.draw())

    def get_outcome(self) -> dict[str, Any]:
        """
        Determine the game outcome and calculate payouts.

        Returns:
            Dictionary containing outcome details and payout information.
        """
        results = {
            "main_hand": self._get_hand_outcome(self.main_hand, self.main_bet),
            "split_hand": None,
            "insurance": None,
            "total_payout": 0
        }

        # Calculate main hand payout
        main_payout = results["main_hand"]["payout"]

        # Calculate split hand payout if applicable
        split_payout = 0
        if self.split_hand:
            results["split_hand"] = self._get_hand_outcome(self.split_hand, self.split_bet)
            split_payout = results["split_hand"]["payout"]

        # Calculate insurance payout if applicable
        insurance_payout = 0
        if self.insurance_bet > 0:
            if self.dealer_hand.is_blackjack:
                # Insurance pays 2:1
                insurance_payout = self.insurance_bet * 2
                results["insurance"] = {
                    "outcome": "win",
                    "bet": self.insurance_bet,
                    "payout": insurance_payout
                }
            else:
                results["insurance"] = {
                    "outcome": "loss",
                    "bet": self.insurance_bet,
                    "payout": 0
                }

        # Calculate total payout
        results["total_payout"] = main_payout + split_payout + insurance_payout

        return results

    def _get_hand_outcome(self, hand: Hand, bet: int) -> dict[str, Any]:
        """
        Determine the outcome for a specific hand.

        Args:
            hand: The hand to evaluate
            bet: The bet amount for this hand

        Returns:
            Dictionary with outcome details
        """
        # Handle surrender
        if self.has_surrendered:
            return {
                "outcome": "surrender",
                "message": "Surrender! Half your bet is returned. 🏳️",
                "bet": bet,
                "payout": bet * OUTCOME_PAYOUTS["surrender"]
            }

        # Handle bust
        if hand.is_busted:
            return {
                "outcome": "loss",
                "message": "Bust! You went over 21. Dealer wins. 💸",
                "bet": bet,
                "payout": 0
            }

        # Handle player blackjack
        if hand.is_blackjack and not self.dealer_hand.is_blackjack:
            return {
                "outcome": "blackjack",
                "message": "Blackjack! Payout is 3:2. 💰💰💰",
                "bet": bet,
                "payout": bet * OUTCOME_PAYOUTS["blackjack"]
            }

        # Handle dealer blackjack
        if self.dealer_hand.is_blackjack and not hand.is_blackjack:
            return {
                "outcome": "loss",
                "message": "Dealer has Blackjack! You lose. 💸",
                "bet": bet,
                "payout": 0
            }

        # Handle push with blackjack
        if hand.is_blackjack and self.dealer_hand.is_blackjack:
            return {
                "outcome": "push",
                "message": "Both have Blackjack! It's a push. 🔄",
                "bet": bet,
                "payout": bet
            }

        # Handle dealer bust
        if self.dealer_hand.is_busted:
            return {
                "outcome": "win",
                "message": "Dealer busts! You win. 💰",
                "bet": bet,
                "payout": bet * OUTCOME_PAYOUTS["win"]
            }

        # Compare hand values for regular outcomes
        if hand.value > self.dealer_hand.value:
            return {
                "outcome": "win",
                "message": "You win! Your hand beats the dealer. 💰",
                "bet": bet,
                "payout": bet * OUTCOME_PAYOUTS["win"]
            }
        elif hand.value < self.dealer_hand.value:
            return {
                "outcome": "loss",
                "message": "Dealer wins! Your hand loses. 💸",
                "bet": bet,
                "payout": 0
            }
        else:
            return {
                "outcome": "push",
                "message": "Push! It's a tie. Your bet is returned. 🔄",
                "bet": bet,
                "payout": bet
            }

    def can_double_down(self) -> bool:
        """Check if the player can double down on the current hand."""
        # Can only double down on initial 2 cards
        return len(self.current_hand.cards) == 2

    def can_surrender(self) -> bool:
        """Check if the player can surrender."""
        # Can only surrender on initial hand with no split
        return (len(self.main_hand.cards) == 2 and
                self.split_hand is None and
                not self.is_complete)

    def create_game_embed(self, reveal_dealer: bool = False) -> hikari.Embed:
        """
        Create an embed displaying the current game state.

        Args:
            reveal_dealer: Whether to reveal the dealer's hidden card

        Returns:
            A hikari.Embed object representing the game state
        """
        embed = hikari.Embed(title="🃏 Blackjack", color=0x2B2D31)

        # Show player's main hand
        main_hand_label = "Your Hand" if self.split_hand is None else "Your First Hand"
        main_hand_value = self.main_hand.value
        has_soft_ace_main = sum(1 for card in self.main_hand.cards if card.face == 'Ace') > 0 and main_hand_value <= 21

        if has_soft_ace_main and main_hand_value != 11:
            hard_total_main = main_hand_value - 10
            value_label = f" (Total: {main_hand_value} / {hard_total_main})"
        else:
            value_label = f" (Total: {self.main_hand.value})"
        embed.add_field(
            name=f"{main_hand_label}{value_label}",
            value=self.main_hand.to_string(),
            inline=False
        )

        # Show split hand if applicable
        if self.split_hand:
            active_marker = " ← Current" if self.active_hand_index == 1 else ""
            split_hand_value = self.split_hand.value
            has_soft_ace_split = sum(1 for card in self.split_hand.cards if card.face == 'Ace') > 0 and split_hand_value <= 21
            if has_soft_ace_split and split_hand_value != 11:
                hard_total_split = split_hand_value - 10
                value_label = f" (Total: {split_hand_value} / {hard_total_split})"
            else:
                value_label = f" (Total: {self.split_hand.value})"
            embed.add_field(
                name=f"Your Second Hand (Total: {split_hand_value} / {split_hand_value + 10}){active_marker}",
                value=self.split_hand.to_string(),
                inline=False
            )

        # Show dealer's hand
        if reveal_dealer:
            embed.add_field(
                name=f"Dealer's Hand (Total: {self.dealer_hand.value})",
                value=self.dealer_hand.to_string(),
                inline=False
            )
        else:
            embed.add_field(
                name="Dealer's Hand",
                value=self.dealer_hand.to_string(hide_second_card=True),
                inline=False
            )

        # Show bet information
        bet_info = f"Main Bet: ${self.main_bet}"
        if self.split_hand:
            bet_info += f" | Split Bet: ${self.split_bet}"
        if self.insurance_bet > 0:
            bet_info += f" | Insurance: ${self.insurance_bet}"

        embed.set_footer(text=bet_info)

        return embed

#endregion

#region Blackjack Menu

class BlackjackMenu(lightbulb.components.Menu):
    """Interactive menu for the blackjack game with buttons for game actions."""

    def __init__(self, game: BlackjackGame) -> None:
        """
        Initialize the menu with buttons based on the game state.

        Args:
            game: The BlackjackGame instance to control
        """
        super().__init__()
        self.game = game

        # Standard game buttons always available
        self.hit_button = self.add_interactive_button(
            hikari.ButtonStyle.SUCCESS,
            self.on_hit,
            label="Hit",
            custom_id="blackjack_hit"
        )
        self.stand_button = self.add_interactive_button(
            hikari.ButtonStyle.DANGER,
            self.on_stand,
            label="Stand",
            custom_id="blackjack_stand"
        )

        # Conditional buttons based on game state
        if self.game.main_hand.can_split and not self.game.split_hand:
            self.split_button = self.add_interactive_button(
                hikari.ButtonStyle.PRIMARY,
                self.on_split,
                label="Split",
                custom_id="blackjack_split"
            )

        if self.game.can_double_down():
            self.double_down_button = self.add_interactive_button(
                hikari.ButtonStyle.PRIMARY,
                self.on_double_down,
                label="Double Down",
                custom_id="blackjack_double_down"
            )

        if self.game.can_surrender():
            self.surrender_button = self.add_interactive_button(
                hikari.ButtonStyle.SECONDARY,
                self.on_surrender,
                label="Surrender",
                custom_id="blackjack_surrender"
            )

        if self.game.insurance_available and not self.game.insurance_resolved:
            self.insurance_button = self.add_interactive_button(
                hikari.ButtonStyle.SUCCESS,
                self.on_insurance,
                label="Insurance",
                custom_id="blackjack_insurance"
            )

    async def predicate(self, ctx: lightbulb.components.MenuContext) -> bool:
        """Check if the user is the player in this game."""
        if ctx.user.id != self.game.player_id:
            await ctx.respond("You are not the player in this game.", flags=hikari.MessageFlag.EPHEMERAL)
            return False
        return True

    async def on_hit(self, ctx: lightbulb.components.MenuContext) -> None:
        """Handle the Hit button action."""
        defer = await ctx.respond(
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE,
            flags=hikari.MessageFlag.EPHEMERAL
        )

        await ctx.delete_response(defer)

        card = self.game.hit()

        # Game continues - show updated state
        content = f"🃏 Hit! You got a {card.suit}{card.face}."
        if self.game.active_hand_index == 1:
            content = f"🃏 Hit on second hand! You got a {card.suit}{card.face}."

        if self.game.is_complete:
            # Game has ended due to bust
            await self._show_game_result(ctx)
            return

        updated_menu = BlackjackMenu(self.game)

        await ctx.client.rest.edit_message(
            channel=ctx.channel_id,
            message=self.game.message_id,
            content=content,
            embed=self.game.create_game_embed(),
            components=updated_menu
        )

    async def on_stand(self, ctx: lightbulb.components.MenuContext) -> None:
        """Handle the Stand button action."""
        defer = await ctx.respond(
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE,
            flags=hikari.MessageFlag.EPHEMERAL
        )

        await ctx.delete_response(defer)

        self.game.stand()

        if self.game.is_complete:
            # Game has ended
            await self._show_game_result(ctx)
            return

        updated_menu = BlackjackMenu(self.game)

        await ctx.edit_response(
            response_id=self.game.message_id,
            content="🃏 Standing on first hand. Playing second hand.",
            embed=self.game.create_game_embed(),
            components=updated_menu
        )

    async def on_double_down(self, ctx: lightbulb.components.MenuContext) -> None:
        """Handle the Double Down button action."""
        defer = await ctx.respond(
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE,
            flags=hikari.MessageFlag.EPHEMERAL
        )

        await ctx.delete_response(defer)

        card = self.game.double_down()

        if self.game.is_complete:
            # Game has ended
            await self._show_game_result(ctx)
            return

        updated_menu = BlackjackMenu(self.game)

        await ctx.client.rest.edit_message(
            channel=ctx.channel_id,
            message=self.game.message_id,
            content=f"🃏 Double Down on first hand! You got a {card.suit}{card.face}. Playing second hand.",
            embed=self.game.create_game_embed(),
            components=updated_menu
        )

    async def on_split(self, ctx: lightbulb.components.MenuContext) -> None:
        """Handle the Split button action."""
        defer = await ctx.respond(
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE,
            flags=hikari.MessageFlag.EPHEMERAL
        )

        await ctx.delete_response(defer)

        updated_menu = BlackjackMenu(self.game)

        if self.game.split():
            await ctx.client.rest.edit_message(
                channel=ctx.channel_id,
                message=self.game.message_id,
                content="🃏 Hand split! Playing first hand.",
                embed=self.game.create_game_embed(),
                components=updated_menu
            )
        else:
            await ctx.respond(
                content="🃏 Cannot split this hand.",
                flags=hikari.MessageFlag.EPHEMERAL
            )

    async def on_surrender(self, ctx: lightbulb.components.MenuContext) -> None:
        """Handle the Surrender button action."""
        if self.game.surrender():
            await self._show_game_result(ctx)
        else:
            await ctx.respond(
                content="🃏 Cannot surrender at this point.",
                flags=hikari.MessageFlag.EPHEMERAL
            )

    async def on_insurance(self, ctx: lightbulb.components.MenuContext) -> None:
        """Handle the Insurance button action."""
        if self.game.take_insurance():
            defer = await ctx.respond(
                hikari.ResponseType.DEFERRED_MESSAGE_UPDATE,
            flags=hikari.MessageFlag.EPHEMERAL
            )
            await ctx.delete_response(defer)
            if self.game.is_complete:
                # Dealer had blackjack - game ends
                await self._show_game_result(ctx)
            else:
                updated_menu = BlackjackMenu(self.game)
                # Game continues
                await ctx.client.rest.edit_message(
                    channel=ctx.channel_id,
                    message=self.game.message_id,
                    content="🃏 Insurance taken. Dealer does not have Blackjack.",
                    embed=self.game.create_game_embed(),
                    components=updated_menu
                )
        else:
            await ctx.respond(
                content="🃏 Insurance not available.",
                flags=hikari.MessageFlag.EPHEMERAL
            )

    async def _show_game_result(self, ctx: lightbulb.components.MenuContext) -> None:
        """Display the final game result and process payout."""
        outcome = self.game.get_outcome()

        # Process payout
        payout = await self._process_payout(
            self.game.player_id,
            outcome["total_payout"],
            self.game.initial_bet,
            ctx,
            outcome,
            self.game.main_hand,
            self.game.dealer_hand
        )

        # Prepare result messages
        result_messages = [outcome["main_hand"]["message"]]

        # Split hand result if applicable
        if outcome["split_hand"]:
            result_messages.append(outcome["split_hand"]["message"])

        # Insurance result if applicable
        if outcome["insurance"]:
            insurance_result = "won" if outcome["insurance"]["outcome"] == "win" else "lost"
            result_messages.append(f"Insurance: You {insurance_result} your insurance bet.")

        # Format the final result message
        result_text = "\n".join(result_messages)
        content = f"🃏 Game Results:\n{result_text}\nTotal Payout: ${outcome['total_payout']}."

        await ctx.user.app.rest.edit_message(
            channel=ctx.channel_id,
            message=self.game.message_id,
            content=content,
            embed=self.game.create_game_embed(reveal_dealer=True),
            components=[]
        )

    async def _process_payout(self,
            user_id: int,
            amount: int,
            bet: int,
            ctx: lightbulb.components.MenuContext,
            outcome: dict[str, Any],
            player_hand: Hand,
            dealer_hand: Hand
    ) -> None:
        """
        Process the payout for an immediate blackjack result.

        Args:
            user_id: The player's user ID
            amount: The amount to pay out
            bet: The original bet amount
        """
        # Calculate net gain/loss (amount includes original bet)
        net_change = amount - bet

        # Update user's balance
        gu.process_gambling_result(
            str(user_id),
            str(ctx.guild_id),
            "blackjack",
            bet,
            amount,
            outcome["main_hand"]["outcome"],
            game_data={
                "player_hand": str(player_hand.cards),
                "dealer_hand": str(dealer_hand.cards),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

#endregion

#region Commands - Blackjack

@blackjack.register()
class BlackjackCommand(
    lightbulb.SlashCommand,
    name="play",
    description="Play a game of blackjack."
):
    bet = lightbulb.integer("bet", "Amount of cash to bet on the game.", min_value=10, max_value=1000)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, cl: lightbulb.Client) -> None:
        """Handle the blackjack command invocation."""
        await ctx.defer()  # Defer the response to avoid timeout issues

        # Check if user has enough
        can_bet, reason = gu.validate_bet(str(ctx.user.id), self.bet)

        if not can_bet:
            await ctx.respond(f"❌ {reason}", flags=hikari.MessageFlag.EPHEMERAL)
            return

        members.update_one(
            {"user_id": str(ctx.user.id)},
            {"$inc": {"cash": -self.bet}}
        )

        msg = await ctx.interaction.fetch_initial_response()
        # Create game instance
        game = BlackjackGame(ctx.user.id, self.bet, msg.id)

        # Check for immediate blackjack scenarios
        if game.is_complete:
            outcome = game.get_outcome()

            # Process payout
            total_payout = outcome["total_payout"]
            player_hand = game.main_hand
            dealer_hand = game.dealer_hand
            await self._process_payout(ctx.user.id, total_payout, self.bet, ctx, outcome, player_hand, dealer_hand)

            # Display result
            if game.main_hand.is_blackjack and game.dealer_hand.is_blackjack:
                await ctx.respond(
                    content="🃏 Both you and the dealer have Blackjack! It's a push.",
                    embed=game.create_game_embed(reveal_dealer=True)
                )
            elif game.main_hand.is_blackjack:
                await ctx.respond(
                    content=f"🃏 Blackjack! You have a natural 21. Payout is 3:2. You win ${total_payout}!",
                    embed=game.create_game_embed(reveal_dealer=True)
                )
            elif game.dealer_hand.is_blackjack:
                await ctx.respond(
                    content=f"🃏 Dealer has Blackjack! You lose your bet of ${self.bet}.",
                    embed=game.create_game_embed(reveal_dealer=True)
                )
            return

        # Create interactive menu
        menu = BlackjackMenu(game)

        # Show initial game state
        content = "🃏 Blackjack game started! Make your move."
        if game.insurance_available:
            content += " The dealer has an Ace, and offers insurance."

        # Use the deferred response
        await ctx.respond(
            content=content,
            embed=game.create_game_embed(),
            components=menu
        )

        # Wait for player interactions
        try:
            await menu.attach(cl, timeout=120)
        except asyncio.TimeoutError:
            # Avoid using ctx.edit_response which can cause interaction issues
            try:
                # Get the message ID from the interaction
                message = await ctx.interaction.fetch_initial_response()
                await ctx.client.app.rest.edit_message(
                    message.channel_id,
                    message.id,
                    content="🃏 Blackjack game timed out. Your bet has been forfeited.",
                    components=[]
                )
            except (hikari.NotFoundError, hikari.ForbiddenError):
                # Handle case where message cannot be edited
                pass

    async def _process_payout(
            self,
            user_id: int,
            amount: int,
            bet: int,
            ctx: lightbulb.Context,
            outcome: dict[str, Any],
            player_hand: Hand,
            dealer_hand: Hand
    ) -> None:
        """
        Process the payout for an immediate blackjack result.

        Args:
            user_id: The player's user ID
            amount: The amount to pay out
            bet: The original bet amount
        """
        # Calculate net gain/loss (amount includes original bet)
        net_change = amount - bet

        # Update user's balance
        gu.process_gambling_result(
            str(user_id),
            str(ctx.guild_id),
            "blackjack",
            bet,
            amount,
            outcome["main_hand"]["outcome"],
            game_data={
                "player_hand": str(player_hand.cards),
                "dealer_hand": str(dealer_hand.cards),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )


@blackjack.register()
class BlackjackHelp(
    lightbulb.SlashCommand,
    name="help",
    description="Get help with playing Blackjack."
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Display comprehensive help information for the blackjack game."""
        embed = hikari.Embed(
            title="🃏 Blackjack Help",
            color=0x2B2D31,
            description="Blackjack is a card game where the goal is to get as close to 21 as possible without going over.",
            timestamp=datetime.now(timezone.utc)
        )

        embed.add_field(
            name="Game Rules",
            value=(
                "• The player and dealer are each dealt two cards.\n"
                "• The player can see both their cards but only one of the dealer's cards.\n"
                "• Number cards (2-10) are worth their face value.\n"
                "• Face cards (Jack, Queen, King) are worth 10 points.\n"
                "• Aces are worth 11 points, but change to 1 point if the total would exceed 21.\n"
                "• The player can choose to hit (draw a card) or stand (end turn).\n"
                "• If the player's total exceeds 21, they bust and lose the game.\n"
                "• The dealer must hit until their hand value is 17 or higher.\n"
                "• The player wins if their final total is higher than the dealer's without busting.\n"
                "• A 'blackjack' is an Ace and a 10-value card on the initial deal (pays 3:2)."
            ),
            inline=False
        )

        embed.add_field(
            name="Special Actions",
            value=(
                "• **Split**: If your initial two cards have the same value, you can split them into two separate hands, each with its own bet.\n"
                "• **Double Down**: Double your bet and receive exactly one more card, then stand automatically.\n"
                "• **Surrender**: Give up your hand and lose only half your bet. Only available on your initial two cards.\n"
                "• **Insurance**: If the dealer's up-card is an Ace, you can place an insurance bet (half your original bet) against the dealer having blackjack. Pays 2:1 if the dealer has blackjack."
            ),
            inline=False
        )

        embed.add_field(
            name="Payouts",
            value=(
                "• **Blackjack**: 3:2 (bet 100, win 150)\n"
                "• **Regular Win**: 1:1 (bet 100, win 100)\n"
                "• **Push** (tie): Bet returned\n"
                "• **Insurance Win**: 2:1 on insurance bet\n"
                "• **Surrender**: Lose half your bet"
            ),
            inline=False
        )

        embed.add_field(
            name="How to Play",
            value=(
                "1. Use `/blackjack bet:[amount]` to start a game with a bet between 10 and 1000 dollars.\n"
                "2. Click on the action buttons to play your hand.\n"
                "3. The game will automatically resolve once all decisions are made.\n"
                "4. Your winnings (or losses) will be automatically calculated and added to your balance."
            ),
            inline=False
        )

        await ctx.respond(embed=embed)

#endregion

#endregion

loader.command(gambling)