#region Imports
from datetime import datetime, timezone, timedelta
import asyncio

import hikari
import lightbulb

from database import members, transactions
from hooks import fail_if_not_admin_or_owner
#endregion

loader = lightbulb.Loader()

#region Utility Functions

def generate_id() -> str:
    """
    Generate a unique identifier for a transaction or record.

    Returns:
        str: A unique identifier.
    """
    import uuid
    return str(uuid.uuid4())

def generate_short_id() -> str:
    """
    Generate a short unique identifier.

    Returns:
        str: A short unique identifier.
    """
    import uuid
    return str(uuid.uuid4())[:8]

def get_user_data(user_id: str) -> dict | None:
    """
    Retrieve user data from the database.

    Args:
        user_id (str): The ID of the user.

    Returns:
        dict | None: The user data if found, otherwise None.
    """
    return members.find_one({"id": user_id})

def update_user_balance(user_id: str, cash_delta: float = 0.0, bank_delta: float = 0.0) -> None:
    """
    Update the user's cash and bank balances.

    Args:
        user_id (str): The ID of the user.
        cash_delta (float): The amount to change the cash balance by.
        bank_delta (float): The amount to change the bank balance by.
    """
    members.update_one(
        {"id": user_id},
        {
            "$inc": {
                "cash": cash_delta,
                "bank": bank_delta
            }
        }
    )

#endregion

#region Transaction Recording

def create_transaction_record(
    user_id_from: str,
    user_id_to: str,
    amount: float,
    description: str,
    transaction_type: str = "payment",
    related_loan_id: str | None = None,
    transaction_status: str = "completed"
) -> str:
    """
    Create a transaction record for a user.

    Args:
        user_id_from (str): The ID of the user sending the money.
        user_id_to (str): The ID of the user receiving the money.
        amount (float): The amount of the transaction.
        description (str): A description of the transaction.
        transaction_type (str): The type of transaction ("payment" or "loan").
        related_loan_id (str | None): The ID of the related loan, if applicable.
        transaction_status (str): The status of the transaction.

    Returns:
        str: The ID of the created transaction.
    """
    transaction_id = generate_id()
    transaction_record = {
        "transaction_id": transaction_id,
        "timestamp": datetime.now(timezone.utc),
        "type": transaction_type,
        "from_account": user_id_from,
        "to_account": user_id_to,
        "amount": amount,
        "description": description,
        "related_loan": related_loan_id,
        "fees_charged": 0.0,  # Fees can be added later if applicable
        "status": transaction_status  # Status of the transaction
    }
    transactions.insert_one(transaction_record)
    return transaction_id

#endregion
