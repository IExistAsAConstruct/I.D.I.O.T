#region Imports
import asyncio
from datetime import datetime, timezone, timedelta

import hikari
import lightbulb

from database import members

#endregion

loader = lightbulb.Loader()

#region Constants
BANK_INTEREST_RATE = 0.005 # Weekly interest rate
LOAN_WEEKLY_RATE_CHANGE = 0.0029 # Weekly rate change (~15% APR)
#endregion

#region Banking Schedules

async def process_bank_interest():
    """
    Process weekly bank interest for all members.
    Runs automatically at Monday, midnight UTC.
    """
    print(f"[{datetime.now(timezone.utc)}] Starting bank interest processing...")
    count = 0
    total_interest = 0

    for user_doc in members.find({"bank": {"$gt": 0}}):
        bank_amount = user_doc.get("bank", 0)
        interest = bank_amount * BANK_INTEREST_RATE

        members.update_one(
            {"id": user_doc["id"]},
            {"$inc": {"bank": interest}}
        )
        count += 1
        total_interest += interest

    print(f"[{datetime.now(timezone.utc)}] Bank interest processed for {count} members. Total interest added: {total_interest:.2f}")

async def process_loan_accrual():
    """
    Process weekly loan accrual for all members.
    Penalizes credit scores for unpaid loans.
    Runs automatically at Monday, midnight UTC.
    """
    print(f"[{datetime.now(timezone.utc)}] Starting loan accrual processing...")
    count = 0
    total_interest = 0

    for user_doc in members.find({"debts": {"$exists": True, "$ne": []}}):
        user_id = user_doc["id"]
        debts = user_doc.get("debts", [])
        updated = False

        for loan in debts:
            if loan["status"] != "active":
                continue

            last_accrual = loan.get("last_accrual")
            if not last_accrual:
                last_accrual = loan.get("created_at")

            if not last_accrual:
                continue

            time_diff = datetime.now(timezone.utc) - last_accrual
            weeks_passed = time_diff.days / 7

            if weeks_passed >= 1:
                apr = loan['apr']
                weekly_rate = apr / 100 / 52
                balance = loan['remaining_balance']
                interest = balance * weekly_rate * int(weeks_passed)

                loan['remaining_balance'] += interest
                loan['last_accrual'] = datetime.now(timezone.utc)
                total_interest += interest

                user_credit_score = user_doc.get("credit_score", 500)
                if user_credit_score > 300:
                    penalty = min(5, int(weeks_passed) * 2)
                    members.update_one(
                        {"id": user_id},
                        {"$inc": {"credit_score": -penalty}}
                    )
                    print(f"[Loan Accrual] User {user_id} credit score decreased by {penalty} points due to unpaid loan.")

                updated = True
                count += 1

        if updated:
            total_debt = sum(loan['remaining_balance'] for loan in debts if loan['status'] == 'active')
            members.update_one(
                {"id": user_id},
                {"$set": {"debts": debts, "total_debt": total_debt}}
            )

    print(f"[{datetime.now(timezone.utc)}] Loan accrual processed for {count} members. Total interest added: {total_interest:.2f}")

@loader.task(lightbulb.crontrigger("0 0 * * 1"))  # Every Monday at midnight UTC
async def weekly_bank_interest() -> None:
    try:
        await process_bank_interest()
    except Exception as e:
        print(f"Error processing bank interest: {e}")

@loader.task(lightbulb.crontrigger("0 0 * * 1"))  # Every Monday at midnight UTC
async def weekly_loan_accrual() -> None:
    try:
        await process_loan_accrual()
    except Exception as e:
        print(f"Error processing loan accrual: {e}")

#endregion