# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from decimal import Decimal, ROUND_UP

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import (
    BankAccount,
    BudgetPreference,
    Expense,
    ExpenseCategory,
    Income,
    IncomeCategory,
    MonthlyExpense,
    RecurringIncome,
    SavingsGoal,
    Transfer,
)


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"
            if field.required:
                field.widget.attrs["required"] = True


class UserScopedFormMixin:
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if "bank_account" in self.fields:
            self.fields["bank_account"].queryset = BankAccount.objects.filter(user=user)
        if "category" in self.fields:
            model = self.fields["category"].queryset.model
            self.fields["category"].queryset = model.objects.filter(user=user)


class BankAccountForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ["name", "balance"]
        labels = {"balance": "Current balance"}
        widgets = {
            "balance": forms.NumberInput(attrs={"step": "0.01"}),
        }


class BudgetPreferenceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = BudgetPreference
        fields = ["expected_daily_expense"]
        labels = {"expected_daily_expense": "Expected spending per day"}
        widgets = {
            "expected_daily_expense": forms.NumberInput(
                attrs={"step": "0.01", "min": "0"}
            )
        }


class DashboardAnimationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = BudgetPreference
        fields = [
            "theme",
            "currency",
            "transaction_deletion_mode",
            "profile_picture",
            "healthy_gif",
            "warning_gif",
            "danger_gif",
        ]
        labels = {
            "theme": "Color theme",
            "currency": "Display currency",
            "transaction_deletion_mode": "When deleting a transaction",
            "profile_picture": "Profile picture",
            "healthy_gif": "On track GIF",
            "warning_gif": "Warning GIF",
            "danger_gif": "Out of budget GIF",
        }
        widgets = {
            "profile_picture": forms.FileInput(
                attrs={"accept": "image/jpeg,image/png,image/webp"}
            ),
            "healthy_gif": forms.FileInput(attrs={"accept": "image/gif"}),
            "warning_gif": forms.FileInput(attrs={"accept": "image/gif"}),
            "danger_gif": forms.FileInput(attrs={"accept": "image/gif"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["theme"].required = False
        self.fields["currency"].required = False
        self.fields["transaction_deletion_mode"].required = False

    def clean_theme(self):
        return (
            self.cleaned_data.get("theme")
            or self.instance.theme
            or BudgetPreference.THEME_OCEAN
        )

    def clean_currency(self):
        return (
            self.cleaned_data.get("currency")
            or self.instance.currency
            or BudgetPreference.CURRENCY_EUR
        )

    def clean_transaction_deletion_mode(self):
        return (
            self.cleaned_data.get("transaction_deletion_mode")
            or self.instance.transaction_deletion_mode
            or BudgetPreference.DELETE_BALANCE_AUTOMATIC
        )


class TransactionForm(UserScopedFormMixin, StyledFormMixin, forms.ModelForm):
    def clean_date(self):
        value = self.cleaned_data["date"]
        if value > timezone.localdate():
            raise forms.ValidationError("Use a recurring plan for future transactions.")
        return value

    def clean_bank_account(self):
        value = self.cleaned_data.get("bank_account")
        if value is None:
            raise forms.ValidationError("Choose a bank account.")
        return value


class ExpenseForm(TransactionForm):
    class Meta:
        model = Expense
        fields = ["text", "amount", "date", "category", "bank_account"]
        labels = {"text": "Description"}
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "date": forms.DateInput(attrs={"type": "date"}),
        }


class IncomeForm(TransactionForm):
    class Meta:
        model = Income
        fields = ["text", "amount", "date", "category", "bank_account"]
        labels = {"text": "Description"}
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "date": forms.DateInput(attrs={"type": "date"}),
        }


class DateRangeForm(UserScopedFormMixin, StyledFormMixin, forms.ModelForm):
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "End date must be on or after the first date.")
        return cleaned_data


class RecurringIncomeForm(DateRangeForm):
    class Meta:
        model = RecurringIncome
        fields = ["name", "amount", "start_date", "end_date", "category", "bank_account"]
        labels = {
            "start_date": "First payment date",
            "end_date": "Stop repeating after (optional)",
        }
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class MonthlyExpenseForm(DateRangeForm):
    class Meta:
        model = MonthlyExpense
        fields = ["name", "amount", "start_date", "end_date", "category", "bank_account"]
        labels = {
            "start_date": "First charge date",
            "end_date": "Stop repeating after (optional)",
        }
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class SavingsGoalForm(UserScopedFormMixin, StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SavingsGoal
        fields = [
            "name",
            "monthly_amount",
            "target_amount",
            "target_date",
            "current_balance",
            "start_date",
            "bank_account",
        ]
        labels = {
            "monthly_amount": "Monthly amount (for an ongoing goal)",
            "target_amount": "Target amount (for a dated goal)",
            "target_date": "Target date",
            "current_balance": "Already saved",
            "start_date": "First monthly saving date",
            "bank_account": "Default funding account",
        }
        widgets = {
            "monthly_amount": forms.NumberInput(
                attrs={"step": "0.01", "min": "0.01"}
            ),
            "target_amount": forms.NumberInput(
                attrs={"step": "0.01", "min": "0.01"}
            ),
            "current_balance": forms.NumberInput(
                attrs={"step": "0.01", "min": "0"}
            ),
            "target_date": forms.DateInput(attrs={"type": "date"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["monthly_amount"].required = False
        self.fields["target_amount"].required = False
        self.fields["target_date"].required = False
        self.fields["bank_account"].required = True
        self.fields["bank_account"].widget.attrs["required"] = True

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        target_date = cleaned_data.get("target_date")
        target_amount = cleaned_data.get("target_amount")
        monthly_amount = cleaned_data.get("monthly_amount")
        current_balance = cleaned_data.get("current_balance") or Decimal("0.00")
        if bool(target_amount) != bool(target_date):
            self.add_error(
                "target_date",
                "Enter both a target amount and target date, or leave both empty.",
            )
        if not target_amount and not monthly_amount:
            self.add_error(
                "monthly_amount",
                "Enter a monthly amount or define a dated target.",
            )
        if start_date and target_date and target_date < start_date:
            self.add_error("target_date", "Target date must be on or after the start date.")
        if target_amount and current_balance > target_amount:
            self.add_error("current_balance", "Saved amount cannot exceed the target.")
        return cleaned_data

    def save(self, commit=True):
        goal = super().save(commit=False)
        goal.end_date = goal.target_date
        if goal.target_amount is not None and goal.start_date and goal.target_date:
            months = (
                (goal.target_date.year - goal.start_date.year) * 12
                + goal.target_date.month
                - goal.start_date.month
                + 1
            )
            remaining = max(goal.target_amount - goal.current_balance, Decimal("0.00"))
            goal.monthly_amount = (
                remaining / max(months, 1)
            ).quantize(Decimal("0.01"), rounding=ROUND_UP)
        if commit:
            goal.save()
            self.save_m2m()
        return goal


class TransferForm(UserScopedFormMixin, StyledFormMixin, forms.ModelForm):
    source = forms.ChoiceField()
    destination = forms.ChoiceField()

    class Meta:
        model = Transfer
        fields = ["name", "amount", "date"]
        labels = {"name": "Description"}
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_destination_goal_id = self.instance.destination_goal_id
        self.order_fields(["name", "amount", "date", "source", "destination"])
        choices = [("", "Choose an account")]
        choices.extend(
            (f"bank:{item.pk}", f"Bank - {item.name}")
            for item in BankAccount.objects.filter(user=self.user)
        )
        choices.extend(
            (f"goal:{item.pk}", f"Goal - {item.name}")
            for item in SavingsGoal.objects.filter(user=self.user, is_archived=False)
        )
        self.fields["source"].choices = choices
        self.fields["destination"].choices = choices
        if self.instance and self.instance.pk:
            self.initial["source"] = self._endpoint_value(
                self.instance.source_bank_id, self.instance.source_goal_id
            )
            self.initial["destination"] = self._endpoint_value(
                self.instance.destination_bank_id, self.instance.destination_goal_id
            )

    @staticmethod
    def _endpoint_value(bank_id, goal_id):
        if bank_id:
            return f"bank:{bank_id}"
        if goal_id:
            return f"goal:{goal_id}"
        return ""

    def clean_date(self):
        value = self.cleaned_data["date"]
        if value > timezone.localdate():
            raise forms.ValidationError("A manual transfer cannot be dated in the future.")
        return value

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("source") == cleaned_data.get("destination"):
            self.add_error("destination", "Source and destination must be different.")
        return cleaned_data

    def _assign_endpoints(self):
        self.instance.source_bank = None
        self.instance.source_goal = None
        self.instance.destination_bank = None
        self.instance.destination_goal = None
        for field_name in ("source", "destination"):
            value = self.cleaned_data.get(field_name)
            if not value:
                continue
            kind, object_id = value.split(":", 1)
            if kind == "bank":
                item = BankAccount.objects.filter(user=self.user, pk=object_id).first()
                setattr(self.instance, f"{field_name}_bank", item)
            else:
                item = SavingsGoal.objects.filter(user=self.user, pk=object_id).first()
                setattr(self.instance, f"{field_name}_goal", item)
        if (
            self.instance.goal_period
            and self.instance.destination_goal_id != self._original_destination_goal_id
        ):
            self.instance.goal_period = None

    def _post_clean(self):
        self.instance.user = self.user
        self._assign_endpoints()
        super()._post_clean()


class CategoryForm(StyledFormMixin, forms.Form):
    name = forms.CharField(max_length=50)


class RegistrationForm(StyledFormMixin, UserCreationForm):
    email = forms.EmailField()

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["username", "email", "password1", "password2"]

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email
