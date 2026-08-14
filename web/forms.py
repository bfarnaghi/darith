# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

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
            self.add_error("end_date", "End date must be on or after the start date.")
        return cleaned_data


class RecurringIncomeForm(DateRangeForm):
    class Meta:
        model = RecurringIncome
        fields = ["name", "amount", "start_date", "end_date", "category", "bank_account"]
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class MonthlyExpenseForm(DateRangeForm):
    class Meta:
        model = MonthlyExpense
        fields = ["name", "amount", "start_date", "end_date", "category", "bank_account"]
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class SavingsGoalForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SavingsGoal
        fields = ["name", "monthly_amount", "start_date", "end_date"]
        labels = {"monthly_amount": "Monthly target"}
        widgets = {
            "monthly_amount": forms.NumberInput(
                attrs={"step": "0.01", "min": "0.01"}
            ),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "End date must be on or after the start date.")
        return cleaned_data


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
