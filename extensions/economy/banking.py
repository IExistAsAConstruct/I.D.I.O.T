from datetime import datetime, timezone

import hikari
import lightbulb

from database import members, transanctions

# Utility Functions

def generate_id() -> str:
    """
    Generate a unique identifier for a transaction or record.

    Returns:
        str: A unique identifier.
    """
    import uuid
    return str(uuid.uuid4())

# Loans

def calculate_weekly_apr(net_received: float, weekly_payment: float, num_weeks: int) -> float:
    """
    Calculate the APR based on the net amount received, weekly payment, and number of weeks.

    Args:
        net_received (float): The net amount received from the loan.
        weekly_payment (float): The weekly payment amount.
        num_weeks (int): The number of weeks over which the loan is repaid.

    Returns:
        float: The APR as a percentage.
    """
    total_paid = weekly_payment * num_weeks
    apr = ((total_paid - net_received) / net_received) * (52 / num_weeks) * 100
    return apr

def calculate_weekly_payment(net_received: float, apr: float, num_weeks: int) -> float:
    """
    Calculate the weekly payment amount based on the net amount received, APR, and number of weeks.

    Args:
        net_received (float): The net amount received from the loan.
        apr (float): The APR as a percentage.
        num_weeks (int): The number of weeks over which the loan is repaid.

    Returns:
        float: The weekly payment amount.
    """
    weekly_apr = apr / 100 / 52
    weekly_payment = net_received * (weekly_apr * (1 + weekly_apr) ** num_weeks) / ((1 + weekly_apr) ** num_weeks - 1)
    return weekly_payment

def can_take_loan(user_id: int, amount: float) -> bool:
    """
    Check if a user can take a loan based on their current debts and total debt.

    Args:
        user_id (int): The ID of the user.
        amount (float): The amount of the loan to be taken.

    Returns:
        bool: True if the user can take the loan, False otherwise.
    """
    user_data = members.find_one({"id": user_id})
    if not user_data:
        return False

    total_debt = user_data.get("total_debt", 0)

    # Check if the new loan would exceed a reasonable debt limit
    return total_debt + amount <= 10000  # Example limit of 10,000 currency units

# Payments and Transanctions

def create_transanction_record(
    user_id_from: int,
    user_id_to: int,
    amount: float,
    description: str,
    transaction_type: str = "payment"
) -> None:
    """
    Create a transaction record for a user.

    Args:
        user_id_from (int): The ID of the user sending the money.
        user_id_to (int): The ID of the user receiving the money.
        amount (float): The amount of the transaction.
        description (str): A description of the transaction.
        transaction_type (str): The type of transaction ("payment" or "loan").
    """
    transanction_record = {
        "transanction_id": generate_id(),
        "timestamp": datetime.now(timezone.utc),
        "type": transaction_type,
        "from_account": user_id_from,
        "to_account": user_id_to,
        "amount": amount,
        "description": description,
        "related_loan": None,  # This can be linked to a specific loan if applicable
        "fees_charged": 0.0,  # Fees can be added later if applicable
        "status": "completed"  # Status of the transaction
    }

    # Insert the transaction record into the database
    transanctions.insert_one(transanction_record)

