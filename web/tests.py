# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import (
    BankAccount,
    Expense,
    ExpenseCategory,
    Income,
    IncomeCategory,
    MonthlyExpense,
    RecurringIncome,
    SavingsGoal,
)
from .services import build_monthly_budget, post_due_recurring


class FinanceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ben", "ben@example.com", "good-password-123")
        self.other_user = User.objects.create_user(
            "other", "other@example.com", "good-password-123"
        )
        self.account = BankAccount.objects.create(
            user=self.user, name="Main", balance=Decimal("1000.00")
        )
        self.expense_category = ExpenseCategory.objects.create(
            user=self.user, name="Food"
        )
        self.income_category = IncomeCategory.objects.create(
            user=self.user, name="Salary"
        )
        self.client.force_login(self.user)

    def test_dashboard_requires_login_and_renders_budget(self):
        self.client.logout()
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Free to spend this month")
        self.assertContains(response, "1,000.00")

    def test_create_update_and_delete_expense_adjusts_balance(self):
        response = self.client.post(
            reverse("create_expense"),
            {
                "text": "Groceries",
                "amount": "75.50",
                "date": "2026-08-10",
                "category": self.expense_category.id,
                "bank_account": self.account.id,
            },
        )
        self.assertEqual(response.status_code, 302)
        expense = Expense.objects.get(text="Groceries")
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("924.50"))

        self.client.post(
            reverse("update_expense", args=[expense.id]),
            {
                "text": "Groceries and lunch",
                "amount": "100.00",
                "date": "2026-08-10",
                "category": self.expense_category.id,
                "bank_account": self.account.id,
            },
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("900.00"))

        self.client.post(reverse("delete_expense", args=[expense.id]))
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))
        self.assertFalse(Expense.objects.filter(pk=expense.id).exists())

    def test_income_can_move_between_accounts_when_edited(self):
        savings = BankAccount.objects.create(
            user=self.user, name="Savings", balance=Decimal("250.00")
        )
        self.client.post(
            reverse("create_income"),
            {
                "text": "Bonus",
                "amount": "200.00",
                "date": "2026-08-10",
                "category": self.income_category.id,
                "bank_account": self.account.id,
            },
        )
        income = Income.objects.get(text="Bonus")
        self.client.post(
            reverse("update_income", args=[income.id]),
            {
                "text": "Bonus",
                "amount": "300.00",
                "date": "2026-08-10",
                "category": self.income_category.id,
                "bank_account": savings.id,
            },
        )
        self.account.refresh_from_db()
        savings.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))
        self.assertEqual(savings.balance, Decimal("550.00"))

    def test_future_manual_transaction_is_rejected(self):
        response = self.client.post(
            reverse("create_expense"),
            {
                "text": "Future",
                "amount": "10.00",
                "date": "2099-01-01",
                "category": self.expense_category.id,
                "bank_account": self.account.id,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Expense.objects.filter(text="Future").exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))

    def test_recurring_income_posts_month_end_once(self):
        plan = RecurringIncome.objects.create(
            user=self.user,
            name="Salary",
            amount=Decimal("100.00"),
            start_date=date(2026, 1, 31),
            end_date=date(2026, 2, 28),
            category=self.income_category,
            bank_account=self.account,
        )
        self.assertEqual(post_due_recurring(self.user, date(2026, 2, 28)), 2)
        self.assertEqual(post_due_recurring(self.user, date(2026, 2, 28)), 0)
        self.assertEqual(
            list(plan.posted_incomes.order_by("date").values_list("date", flat=True)),
            [date(2026, 1, 31), date(2026, 2, 28)],
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1200.00"))

    def test_recurring_expense_posts_and_updates_balance(self):
        plan = MonthlyExpense.objects.create(
            user=self.user,
            name="Rent",
            amount=Decimal("450.00"),
            start_date=date(2026, 8, 5),
            end_date=None,
            category=self.expense_category,
            bank_account=self.account,
        )
        self.assertEqual(post_due_recurring(self.user, date(2026, 8, 14)), 1)
        expense = plan.posted_expenses.get()
        self.assertEqual(expense.date, date(2026, 8, 5))
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("550.00"))

    def test_monthly_budget_projects_plans_and_savings(self):
        RecurringIncome.objects.create(
            user=self.user,
            name="Salary",
            amount=Decimal("2000.00"),
            start_date=date(2026, 8, 25),
            category=self.income_category,
            bank_account=self.account,
        )
        MonthlyExpense.objects.create(
            user=self.user,
            name="Rent",
            amount=Decimal("500.00"),
            start_date=date(2026, 8, 20),
            category=self.expense_category,
            bank_account=self.account,
        )
        SavingsGoal.objects.create(
            user=self.user,
            name="Emergency fund",
            monthly_amount=Decimal("400.00"),
            start_date=date(2026, 1, 1),
        )

        budget = build_monthly_budget(self.user, date(2026, 8, 14))
        self.assertEqual(budget["expected_income"], Decimal("2000.00"))
        self.assertEqual(budget["expected_expenses"], Decimal("500.00"))
        self.assertEqual(budget["savings_target"], Decimal("400.00"))
        self.assertEqual(budget["free_to_spend"], Decimal("2100.00"))
        self.assertEqual(budget["status"], "healthy")

    def test_budget_warns_when_commitments_are_not_covered(self):
        self.account.balance = Decimal("100.00")
        self.account.save()
        SavingsGoal.objects.create(
            user=self.user,
            name="Emergency fund",
            monthly_amount=Decimal("400.00"),
            start_date=date(2026, 1, 1),
        )
        budget = build_monthly_budget(self.user, date(2026, 8, 14))
        self.assertEqual(budget["free_to_spend"], Decimal("-300.00"))
        self.assertEqual(budget["status"], "danger")
        self.assertIn("short by", budget["warning"])

    def test_user_cannot_edit_another_users_account(self):
        private_account = BankAccount.objects.create(
            user=self.other_user, name="Private", balance=Decimal("900.00")
        )
        response = self.client.post(
            reverse("update_bank_account", args=[private_account.id]),
            {"name": "Stolen", "balance": "0.00"},
        )
        self.assertEqual(response.status_code, 404)
        private_account.refresh_from_db()
        self.assertEqual(private_account.name, "Private")
        self.assertEqual(private_account.balance, Decimal("900.00"))

    def test_bank_account_crud(self):
        self.client.post(
            reverse("create_bank_account"),
            {"name": "Travel", "balance": "300.00"},
        )
        account = BankAccount.objects.get(user=self.user, name="Travel")
        self.client.post(
            reverse("update_bank_account", args=[account.id]),
            {"name": "Holiday", "balance": "450.00"},
        )
        account.refresh_from_db()
        self.assertEqual(account.name, "Holiday")
        self.assertEqual(account.balance, Decimal("450.00"))
        self.client.post(reverse("delete_bank_account", args=[account.id]))
        self.assertFalse(BankAccount.objects.filter(pk=account.id).exists())

    def test_recurring_plan_and_savings_goal_crud(self):
        self.client.post(
            reverse("create_recurring_income"),
            {
                "name": "Contract",
                "amount": "800.00",
                "start_date": "2027-01-15",
                "end_date": "2027-12-15",
                "category": self.income_category.id,
                "bank_account": self.account.id,
            },
        )
        plan = RecurringIncome.objects.get(user=self.user, name="Contract")
        self.client.post(
            reverse("update_recurring_income", args=[plan.id]),
            {
                "name": "Client contract",
                "amount": "900.00",
                "start_date": "2027-01-15",
                "end_date": "2027-12-15",
                "category": self.income_category.id,
                "bank_account": self.account.id,
            },
        )
        plan.refresh_from_db()
        self.assertEqual(plan.amount, Decimal("900.00"))
        self.client.post(reverse("delete_recurring_income", args=[plan.id]))
        self.assertFalse(RecurringIncome.objects.filter(pk=plan.id).exists())

        self.client.post(
            reverse("create_savings_goal"),
            {
                "name": "Holiday",
                "monthly_amount": "150.00",
                "start_date": "2027-01-01",
                "end_date": "",
            },
        )
        goal = SavingsGoal.objects.get(user=self.user, name="Holiday")
        self.client.post(reverse("delete_savings_goal", args=[goal.id]))
        self.assertFalse(SavingsGoal.objects.filter(pk=goal.id).exists())

    def test_category_crud(self):
        self.client.post(reverse("create_category", args=["expense"]), {"name": "Travel"})
        category = ExpenseCategory.objects.get(user=self.user, name="Travel")
        self.client.post(
            reverse("update_category", args=["expense", category.id]),
            {"name": "Trips"},
        )
        category.refresh_from_db()
        self.assertEqual(category.name, "Trips")
        self.client.post(reverse("delete_category", args=["expense", category.id]))
        self.assertFalse(ExpenseCategory.objects.filter(pk=category.id).exists())

    def test_deleting_account_keeps_transaction_history(self):
        expense = Expense.objects.create(
            user=self.user,
            text="Coffee",
            amount=Decimal("3.00"),
            date=date(2026, 8, 1),
            category=self.expense_category,
            bank_account=self.account,
        )
        self.client.post(reverse("delete_bank_account", args=[self.account.id]))
        expense.refresh_from_db()
        self.assertIsNone(expense.bank_account)


class RegistrationTests(TestCase):
    def test_registration_saves_email_and_logs_user_in(self):
        response = self.client.post(
            reverse("create_account"),
            {
                "username": "new-user",
                "email": "new@example.com",
                "password1": "a-strong-password-123",
                "password2": "a-strong-password-123",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        user = User.objects.get(username="new-user")
        self.assertEqual(user.email, "new@example.com")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.id)
