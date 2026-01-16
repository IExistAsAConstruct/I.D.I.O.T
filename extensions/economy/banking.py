#region Imports
from datetime import datetime, timezone, timedelta
import asyncio

import hikari
import lightbulb

from database import members, transactions
import extensions.economy.economy_util as eu
from hooks import fail_if_not_admin_or_owner
#endregion

#region Loader Setup
loader = lightbulb.Loader()
banking = lightbulb.Group("bank", "Banking related commands")
loan = banking.subgroup("loan", "Loan related commands",)
#endregion

#region Variables and Constants
BANK_INTEREST_RATE = 0.005 # Weekly interest rate
LOAN_BASE_APR = 15.0  # Base APR for loans
LOAN_MIN_WEEKS = 2
LOAN_MAX_WEEKS = 12
LOAN_MIN_AMOUNT = 100.0
LOAN_MAX_AMOUNT = 5000.0
MAX_TOTAL_DEBT = 10000.0  # Maximum total debt a user can have
BANK_ID = "1399230814679601172"  # Bot's bank ID
#endregion

#region Credit Score System

def calculate_credit_score_modifier(credit_score: int) -> float:
    """
    Calculate the APR modifier based on the user's credit score.
    Higher credit scores result in lower APR modifiers.

    Args:
        credit_score (int): The user's credit score.

    Returns:
        float: The APR modifier.
    """
    if credit_score >= 750:
        return 0.5  # 50% reduction for excellent credit
    elif credit_score >= 650:
        return 0.75  # 25% reduction for good credit
    elif credit_score >= 550:
        return 1.0  # No change for fair credit
    elif credit_score >= 450:
        return 1.5  # 50% increase for poor credit
    else:
        return 2.0  # 100% increase for very poor credit

def adjust_credit_score(user_id: str, delta: int) -> None:
    """
    Adjust the user's credit score by a given delta. Clamped between 300 and 850.

    Args:
        user_id (str): The ID of the user.
        delta (int): The amount to adjust the credit score by.
    """
    user_data = eu.get_user_data(user_id)
    if not user_data:
        return

    current_score = user_data.get("credit_score", 500)
    new_score = max(300, min(850, current_score + delta))

    members.update_one(
        {"id": user_id},
        {"$set": {"credit_score": new_score}}
    )

#endregion

#region Loan Calculations

def calculate_apr_for_user(user_id: str, base_apr: float = LOAN_BASE_APR) -> float:
    """
    Calculate the APR for a user based on their credit score.

    Args:
        user_id (str): The ID of the user.
        base_apr (float): The base APR before adjustment.

    Returns:
        float: The adjusted APR based on the user's credit score as a percentage.
    """
    user_data = eu.get_user_data(user_id)
    if not user_data:
        return base_apr

    credit_score = user_data.get("credit_score", 500)
    modifier = calculate_credit_score_modifier(credit_score)

    return base_apr * modifier

def calculate_weekly_payment(principal: float, apr: float, num_weeks: int) -> float:
    """
    Calculate the weekly payment amount based on the principal, APR, and number of weeks.

    Args:
        principal (float): The amount of the loan.
        apr (float): The APR as a percentage.
        num_weeks (int): The number of weeks over which the loan is repaid.

    Returns:
        float: The weekly payment amount.
    """
    if apr == 0:
        return principal / num_weeks

    weekly_apr = apr / 100 / 52
    weekly_payment = principal * (weekly_apr * (1 + weekly_apr) ** num_weeks) / ((1 + weekly_apr) ** num_weeks - 1)
    return weekly_payment

def calculate_total_interest(principal: float, weekly_payment: float, num_weeks: int) -> float:
    """
    Calculate the total interest paid over the life of the loan.

    Args:
        principal (float): The amount of the loan.
        weekly_payment (float): The weekly payment amount.
        num_weeks (int): The number of weeks over which the loan is repaid.

    Returns:
        float: The total interest paid.
    """
    total_paid = weekly_payment * num_weeks
    total_interest = total_paid - principal
    return total_interest

def can_take_loan(user_id: str, amount: float) -> tuple[bool, str]:
    """
    Check if a user can take a loan based on their current debts and total debt.

    Args:
        user_id (str): The ID of the user.
        amount (float): The amount of the loan to be taken.

    Returns:
        tuple[bool, str]: A tuple containing a boolean indicating if the user can take the loan,
                          and a message explaining the reason.
    """
    user_data = eu.get_user_data(user_id)
    if not user_data:
        return False, "User not found."

    total_debt = user_data.get("total_debt", 0)
    credit_score = user_data.get("credit_score", 500)

    if credit_score < 350:
        return False, "Your credit score is too low to take a loan."

    if total_debt + amount > MAX_TOTAL_DEBT:
        return False, "Taking this loan would exceed your maximum allowed debt."

    if amount < LOAN_MIN_AMOUNT or amount > LOAN_MAX_AMOUNT:
        return False, f"Loan amount must be between {LOAN_MIN_AMOUNT} and {LOAN_MAX_AMOUNT}."

    return True, "Loan approved."

#endregion

#region Loan Management

def create_loan(user_id: str, principal: float, apr: float, num_weeks: int) -> str:
    """
    Create a loan record for a user.

    Args:
        user_id (str): The ID of the user taking the loan.
        principal (float): The amount of the loan.
        apr (float): The APR as a percentage.
        num_weeks (int): The number of weeks over which the loan is repaid.

    Returns:
        str: The ID of the created loan.
    """
    loan_id = eu.generate_short_id()
    weekly_payment = calculate_weekly_payment(principal, apr, num_weeks)
    total_interest = calculate_total_interest(principal, weekly_payment, num_weeks)

    loan_record = {
        "loan_id": loan_id,
        "principal": principal,
        "remaining_balance": principal,
        "apr": apr,
        "weekly_payment": weekly_payment,
        "num_weeks": num_weeks,
        "weeks_remaining": num_weeks,
        "total_interest": total_interest,
        "created_at": datetime.now(timezone.utc),
        "last_accrual": datetime.now(timezone.utc),
        "status": "active"  # Status of the loan
    }

    members.update_one(
        {"id": user_id},
        {
            "$push": {"debts": loan_record},
            "$inc": {"total_debt": principal}
        }
    )

    eu.update_user_balance(user_id, cash_delta=principal)

    adjust_credit_score(user_id, -5)

    eu.create_transaction_record(
        user_id_from=BANK_ID,  # Bank's user ID
        user_id_to=user_id,
        amount=principal,
        description=f"Loan disbursement - {num_weeks} weeks at {apr:.2f}% APR",
        transaction_type="loan_disbursement",
        related_loan_id=loan_id,
        transaction_status="completed"
    )

    return loan_id

def make_loan_payment(user_id: str, loan_id: str, amount: float) -> tuple[bool, str]:
    """
    Make a payment towards a specific loan.

    Args:
        user_id (str): The ID of the user making the payment.
        loan_id (str): The ID of the loan to which the payment is being made.
        amount (float): The amount of the payment.

    Returns:
        tuple[bool, str]: A tuple containing a boolean indicating if the payment was successful,
                          and a message explaining the result.
    """
    user_data = eu.get_user_data(user_id)
    if not user_data:
        return False, "User not found."

    cash = user_data.get("cash", 0)
    if cash < amount:
        return False, "Insufficient funds to make the payment."

    debts = user_data.get("debts", [])
    loan_found = False

    for loan in debts:
        if loan["loan_id"] == loan_id:
            loan_found = True
            remaining = loan["remaining_balance"]

            if amount > remaining:
                return False, f"Payment exceeds remaining loan balance of {remaining:.2f}."

            loan["remaining_balance"] -= amount
            loan["weeks_remaining"] -= max(0, loan["weeks_remaining"] - 1)

            if loan["remaining_balance"] <= 0.01:
                loan["status"] = "paid_off"
                loan["remaining_balance"] = 0.0
                adjust_credit_score(user_id, 20)

            break

    if not loan_found:
        return False, "Loan not found."

    eu.update_user_balance(user_id, cash_delta=-amount)

    members.update_one(
        {"id": user_id},
        {
            "$set": {"debts": debts},
            "$inc": {"total_debt": -amount}
        }
    )

    eu.create_transaction_record(
        user_id_from=user_id,
        user_id_to=BANK_ID,  # Bank's user ID
        amount=amount,
        description=f"Loan payment - Loan ID: {loan_id}",
        transaction_type="loan_payment",
        related_loan_id=loan_id,
        transaction_status="completed"
    )

    return True, f"Payment of {amount:.2f} successful."

#endregion

#region Commands - Basic Banking

@banking.register()
class Balance(
    lightbulb.SlashCommand,
    name="balance",
    description="Check your balance and financial status."
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """
        Display the user's cash balance, bank balance, total debt, and credit score.
        """
        user_id = str(ctx.user.id)
        user_data = eu.get_user_data(str(ctx.user.id))
        if not user_data:
            await ctx.respond("User data not found.")
            return

        cash = user_data.get("cash", 0.0)
        bank_balance = user_data.get("bank", 0.0)
        total_debt = user_data.get("total_debt", 0.0)
        credit_score = user_data.get("credit_score", 500)

        net_worth = cash + bank_balance - total_debt

        embed = hikari.Embed(
            title=f"💰 {ctx.user.display_name}'s Financial Summary",
            color=0x2ECC71 if net_worth >= 0 else 0xE74C3C
        )
        embed.add_field(name="💵 Cash Balance", value=f"${cash:.2f}", inline=False)
        embed.add_field(name="🏦 Bank Balance", value=f"${bank_balance:.2f}", inline=False)
        embed.add_field(name="💳 Total Debt", value=f"${total_debt:.2f}", inline=False)
        embed.add_field(name="📊 Credit Score", value=f"{credit_score}", inline=False)
        embed.add_field(name="💎 Net Worth", value=f"{net_worth:.2f}", inline=True)

        await ctx.respond(embed=embed)

@banking.register()
class Deposit(
    lightbulb.SlashCommand,
    name="deposit",
    description="Deposit cash into your bank account."
):
    amount = lightbulb.number("amount", "Amount of cash to deposit", min_value=1.0)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """
        Deposit a specified amount of cash into the user's bank account.
        """
        user_id = str(ctx.user.id)
        user_data = eu.get_user_data(user_id)
        if not user_data:
            await ctx.respond("User data not found.")
            return

        cash = user_data.get("cash", 0.0)
        amount = self.amount

        if cash < amount:
            await ctx.respond(f"Insufficient cash to deposit that amount. You have {cash:.2f} available.")
            return

        eu.update_user_balance(user_id, cash_delta=-amount, bank_delta=amount)

        eu.create_transaction_record(
            user_id_from=user_id,
            user_id_to=BANK_ID,  # Bank's user ID
            amount=amount,
            description="Bank deposit",
            transaction_type="deposit"
        )

        await ctx.respond(f"✅ Successfully deposited ${amount:.2f} into your bank account.")

@banking.register()
class Withdraw(
    lightbulb.SlashCommand,
    name="withdraw",
    description="Withdraw cash from your bank account."
):
    amount = lightbulb.number("amount", "Amount of cash to withdraw", min_value=1.0)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """
        Withdraw a specified amount of cash from the user's bank account.
        """
        user_id = str(ctx.user.id)
        user_data = eu.get_user_data(user_id)
        if not user_data:
            await ctx.respond("User data not found.")
            return

        bank_balance = user_data.get("bank", 0.0)
        amount = self.amount

        if bank_balance < amount:
            await ctx.respond(f"Insufficient funds in bank to withdraw that amount. You have {bank_balance:.2f} available.")
            return

        eu.update_user_balance(user_id, cash_delta=amount, bank_delta=-amount)

        eu.create_transaction_record(
            user_id_from=BANK_ID,  # Bank's user ID
            user_id_to=user_id,
            amount=amount,
            description="Bank withdrawal",
            transaction_type="withdrawal"
        )

        await ctx.respond(f"✅ Successfully withdrew ${amount:.2f} from your bank account.")

#endregion

#region Commands - Loans

@loan.register()
class LoanRequest(
    lightbulb.SlashCommand,
    name="request",
    description="Request a loan from the bank."
):
    principal = lightbulb.number("principal", "Amount of loan to request", min_value=LOAN_MIN_AMOUNT, max_value=LOAN_MAX_AMOUNT)
    weeks = lightbulb.integer("weeks", "Number of weeks to repay the loan (2-12)", min_value=LOAN_MIN_WEEKS, max_value=LOAN_MAX_WEEKS, default=4)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """
        Process a loan request from the user.
        """
        user_id = str(ctx.user.id)
        amount = self.principal
        weeks = self.weeks

        can_loan, message = can_take_loan(user_id, amount)
        if not can_loan:
            await ctx.respond(f"❌ Loan request denied: {message}")
            return

        apr = calculate_apr_for_user(user_id)
        weekly_payment = calculate_weekly_payment(amount, apr, weeks)
        total_interest = calculate_total_interest(amount, weekly_payment, weeks)
        total_repayment = amount + total_interest

        loan_id = create_loan(user_id, amount, apr, weeks)

        embed = hikari.Embed(
            title="🏦 Loan Approved!",
            description=f"Your loan of ${amount:.2f} has been approved.",
            color=0x3498DB
        )

        embed.add_field(name="📊 APR", value=f"{apr:.2f}%", inline=True)
        embed.add_field(name="📅 Term", value=f"{weeks} weeks", inline=True)
        embed.add_field(name="💰 Weekly Payment", value=f"{weekly_payment:.2f}", inline=True)
        embed.add_field(name="💸 Total Interest", value=f"{total_interest:.2f}", inline=True)
        embed.add_field(name="💳 Total Repayment", value=f"{total_repayment:.2f}", inline=True)

        embed.set_footer(text=f"Loan ID: {loan_id} | Use /bank loan pay to make payments.")

        await ctx.respond(embed=embed)

@loan.register()
class LoanView(
    lightbulb.SlashCommand,
    name="view",
    description="View your current loans."
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """
        Display the user's current loans and their statuses.
        """
        user_id = str(ctx.user.id)
        user_data = eu.get_user_data(user_id)

        if not user_data:
            await ctx.respond("User data not found.")
            return

        debts = user_data.get("debts", [])
        active_loans = [loan for loan in debts if loan["status"] == "active"]

        if not active_loans:
            await ctx.respond("You have no active loans.")
            return

        embed = hikari.Embed(
            title="📋 Your Active Loans",
            color=0xF1C40F
        )

        for idx, loan in enumerate(active_loans, 1):
            loan_info = (
                f"**Balance:** ${loan['remaining_balance']:.2f}\n"
                f"**Weekly Payment:** {loan['weekly_payment']:.2f}\n"
                f"**Weeks Remaining:** {loan['weeks_remaining']}\n"
                f"**APR:** {loan['apr']:.2f}%\n",
                f"**Loan ID:** `{loan['loan_id']}`"
            )
            embed.add_field(name=f"Loan {idx}", value="\n".join(loan_info), inline=False)

        total_debt = user_data.get("total_debt", 0.0)
        embed.set_footer(text=f"Total Debt: ${total_debt:.2f}")

        await ctx.respond(embed=embed)

@loan.register()
class LoanPay(
    lightbulb.SlashCommand,
    name="pay",
    description="Make a payment towards a loan."
):
    loan_id = lightbulb.string("loan_id", "The ID of the loan to pay off")
    amount = lightbulb.number("amount", "Amount to pay towards the loan (0 for weekly payment)", min_value=0.0)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """
        Process a loan payment from the user.
        """
        user_id = str(ctx.user.id)
        loan_id = self.loan_id
        amount = self.amount

        user_data = eu.get_user_data(user_id)
        if not user_data:
            await ctx.respond("User data not found.")
            return

        debts = user_data.get("debts", [])
        matching_loan = None

        for loan in debts:
            if loan["loan_id"] == loan_id and loan["status"] == "active":
                matching_loan = loan
                break

        if not matching_loan:
            await ctx.respond("❌ Loan not found or already paid off.")
            return

        if amount == 0:
            amount = matching_loan["weekly_payment"]

        success, message = make_loan_payment(user_id, loan_id, amount)
        if success:
            remaining = matching_loan["remaining_balance"] - amount

            if remaining <= 0.01:
                await ctx.respond(f"🎉 Loan paid off! {message}\n+20 credit score for paying off your loan!")
            else:
                await ctx.respond(f"✅ {message}\nRemaining balance: ${remaining:.2f}")
        else:
            await ctx.respond(f"❌ Payment failed: {message}")

#endregion

#region Commands - Admin

@banking.register()
class AdminAdjust(
    lightbulb.SlashCommand,
    name="adjust",
    description="Adjust a user's balance (Admin only).",
    hooks=[fail_if_not_admin_or_owner]
):
    user = lightbulb.user("user", "The user to adjust")
    cash_amount = lightbulb.number("cash_amount", "Amount to adjust cash by (use negative for deduction)", default=0.0)
    bank_amount = lightbulb.number("bank_amount", "Amount to adjust bank by (use negative for deduction)", default=0.0)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """
        Adjust a specified user's cash and/or bank balance by given amounts.
        """
        target_user_id = str(self.user.id)
        cash_delta = self.cash_amount
        bank_delta = self.bank_amount

        user_data = eu.get_user_data(target_user_id)
        if not user_data:
            await ctx.respond("User data not found.", ephemeral=True)
            return

        eu.update_user_balance(target_user_id, cash_delta=cash_delta, bank_delta=bank_delta)

        eu.create_transaction_record(
            user_id_from=str(ctx.user.id),
            user_id_to=target_user_id,
            amount=abs(cash_delta) + abs(bank_delta),
            description=f"Admin adjustment by {ctx.user.display_name}",
            transaction_type="admin_adjustment"
        )

        await ctx.respond(
            f"✅ Successfully adjusted <@{target_user_id}>'s balance:\n"
            f"Cash {'+' if cash_delta >= 0 else ''}{cash_delta}\n"
            f"Bank {'+' if bank_delta >= 0 else ''}{bank_delta}.",
            ephemeral=True
        )

#endregion

loader.command(banking)