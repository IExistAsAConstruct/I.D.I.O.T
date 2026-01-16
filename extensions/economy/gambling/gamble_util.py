#region Imports
from datetime import datetime, timezone, timedelta

import hikari
import lightbulb

from database import members, gambling_history
from extensions.economy.economy_util import create_transaction_record, generate_short_id
#endregion

loader = lightbulb.Loader()
BANK_ID = "1399230814679601172"  # Bot's bank ID

#region Gambling Record
def create_gambling_history_record(
        player_id: str,
        guild_id: str,
        game_type: str,
        result: str,
        bet_amount: float,
        payout_amount: float,
        game_data: dict = None
) -> str:
    """
    Create a gambling history record in the database.

    Args:
        player_id (str): The ID of the player.
        guild_id (str): The ID of the guild where the game was played.
        game_type (str): The type of gambling game played.
        result (str): The result of the game ("win", "loss", or "push").
        bet_amount (float): The amount bet by the player.
        payout_amount (float): The amount won by the player (0 if lost).
        game_data (dict, optional): Additional data about the game.

    Returns:
        str: The ID of the created gambling history record.
    """
    record_id = generate_short_id()
    record = {
        "id": record_id,
        "player_id": player_id,
        "guild_id": guild_id,
        "game_type": game_type,
        "result": result,
        "bet_amount": bet_amount,
        "payout_amount": payout_amount,
        "timestamp": datetime.now(timezone.utc),
        "game_data": game_data or {}
    }
    gambling_history.insert_one(record)
    return record_id
#endregion

#region Bet Validation
def validate_bet(user_id: str, bet_amount: float) -> tuple[bool, str]:
    """
    Check if user can place this bet.

    Args:
        user_id (str): The ID of the user placing the bet.
        bet_amount (float): The amount the user wants to bet.

    Returns:
        tuple[bool, str]: A tuple where the first element is True if the bet is valid,
                          and False otherwise. The second element is an error message if invalid.
    """

    user_data = members.find_one({"id": user_id})
    if not user_data:
        return False, "User not found."

    current_cash = user_data.get("cash", 0)

    if current_cash < bet_amount:
        return False, "Insufficient funds to place this bet."

    return True, ""
#endregion

#region Racing Result Processing
def deduct_bet(user_id: str, bet_amount: float, bet_type: str, game_type: str) -> None:
    """
    Deduct the bet amount from the user's cash and create a transaction record.

    Args:
        user_id (str): The ID of the user placing the bet.
        bet_amount (float): The amount of the bet.
        bet_type (str): The type of bet placed.
        game_type (str): The type of gambling game played.
    """
    members.update_one(
        {"id": user_id},
        {"$inc": {"cash": -bet_amount}}
    )

    create_transaction_record(
        user_id_from=user_id,
        user_id_to=BANK_ID,
        amount=bet_amount,
        description=f"Bet on {game_type} ({bet_type})",
        transaction_type="gambling bet"
    )

def process_racing_payout(
    user_id: str,
    guild_id: str,
    payment_amount: float,
    result: str,
    bet_amount: float,
    game_type: str,
    game_data: dict = None
) -> str:
    """
    Process the payout for a racing game.

    Args:
        user_id (str): The ID of the user receiving the payout.
        guild_id (str): The ID of the guild where the game was played.
        payment_amount (float): The amount to be paid out to the user.
        result (str): The result of the game ("win" or "loss").
        bet_amount (float): The amount bet by the user.
        game_type (str): The type of gambling game played.
        game_data (dict, optional): Additional data about the game.

    Returns:
        str: A reference id for the history of the gambling game.
    """
    if result == "win":
        members.update_one(
            {"id": user_id},
            {
                "$inc": {
                    "cash": payment_amount,
                    "wins": 1
                }
            }
        )
        create_transaction_record(
            user_id_from=BANK_ID,
            user_id_to=user_id,
            amount=payment_amount,
            description=f"Won {game_type}",
            transaction_type="gambling payout"
        )
    elif result == "loss":
        members.update_one(
            {"id": user_id},
            {
                "$inc": {
                    "losses": 1
                }
            }
        )

    return create_gambling_history_record(
        player_id=user_id,
        guild_id=guild_id,
        game_type=game_type,
        result=result,
        bet_amount=bet_amount,
        payout_amount=payment_amount,
        game_data=game_data
    )
#endregion

#region Atomic Gambling Result Processing
def process_gambling_result(
        user_id: str,
        guild_id: str,
        game_type: str, # "slots", "racing", "blackjack"
        bet_amount: float,
        payout_amount: float,
        result: str,  # "win", "loss", or "push"
        game_data: dict = None
) -> str:
    """
    Handle all database updates for a completed game.

    Args:
        user_id (str): The ID of the user who played.
        guild_id (str): The ID of the guild where the game was played.
        game_type (str): The type of gambling game played.
        bet_amount (float): The amount bet by the user.
        payout_amount (float): The amount won by the user (0 if lost).
        result (str): The result of the game ("win", "loss", or "push").
        game_data (dict, optional): Additional data about the game.

    Returns:
        str: A reference id for the history of the gambling game.
    """
    user_data = members.find_one({"id": user_id})
    if not user_data:
        return "User not found."

    if game_type is not "blackjack":
        members.update_one(
            {"id": user_id},
            {"$inc": {"cash": -bet_amount}}
        )

    create_transaction_record(
        user_id_from=user_id,
        user_id_to=BANK_ID,
        amount=bet_amount,
        description=f"Bet on {game_type}",
        transaction_type="gambling bet"
    )

    # Update user's cash based on result
    if result == "win":
        members.update_one(
            {"id": user_id},
            {
                "$inc": {
                    "cash": payout_amount,
                    "wins": 1
                }
            }
        )
        create_transaction_record(
            user_id_from=BANK_ID,
            user_id_to=user_id,
            amount=payout_amount,
            description=f"Won {game_type}",
            transaction_type="gambling payout"
        )
    elif result == "loss":
        members.update_one(
            {"id": user_id},
            {
                "$inc": {
                    "losses": 1
                }
            }
        )
    # For "push", no cash change
    else:
        members.update_one(
            {"id": user_id},
            {"$inc": {"cash": bet_amount}}
        )

    # Record the gambling history
    record_id = create_gambling_history_record(
        player_id=user_id,
        guild_id=guild_id,
        game_type=game_type,
        result=result,
        bet_amount=bet_amount,
        payout_amount=payout_amount,
        game_data=game_data
    )

    return record_id
#endregion

def get_user_gambling_stats(user_id: str) -> dict:
    """
    Retrieve overall gambling statistics for a user.

    Args:
        user_id (str): The ID of the user.

    Returns:
        dict: A dictionary containing total bets, wins, losses, and net profit/loss.
    """
    user_data = members.find_one({"id": user_id})
    if not user_data:
        return {}

    total_wins = user_data.get("wins", 0)
    total_losses = user_data.get("losses", 0)

    all_bets = list(gambling_history.find({"player_id": user_id}))

    total_wagered = sum(bet["bet_amount"] for bet in all_bets)
    total_won = sum(bet["payout_amount"] for bet in all_bets if bet["result"] == "win")
    net_profit = total_won - total_wagered

    games = {}
    for bet in all_bets:
        game = bet["game_type"]
        if game not in games:
            games[game] = {"bets": 0, "wagered": 0, "won": 0}
        games[game]["bets"] += 1
        games[game]["wagered"] += bet["bet_amount"]
        if bet["result"] == "win":
            games[game]["won"] += bet["payout_amount"]

    return {
        "total_wins": total_wins,
        "total_losses": total_losses,
        "total_games": len(all_bets),
        "total_wagered": total_wagered,
        "total_won": total_won,
        "net_profit": net_profit,
        "games": games
    }