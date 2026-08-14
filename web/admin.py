# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from django.contrib import admin

from .models import (
    BankAccount,
    Expense,
    ExpenseCategory,
    Income,
    IncomeCategory,
    MonthlyExpense,
    RecurringIncome,
    SavingsGoal,
    Token,
)


admin.site.register(
    [
        BankAccount,
        Expense,
        ExpenseCategory,
        Income,
        IncomeCategory,
        MonthlyExpense,
        RecurringIncome,
        SavingsGoal,
        Token,
    ]
)
