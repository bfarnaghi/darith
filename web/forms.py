# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from decimal import Decimal, ROUND_UP

from django import forms
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import (
    BankAccount,
    BudgetPreference,
    Expense,
    ExpenseCategory,
    Income,
    IncomeCategory,
    MonthlyExpense,
    PlanOccurrence,
    RecurringIncome,
    SavingsGoal,
    Transfer,
    UserFeedback,
)


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
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
        fields = ["name", "balance", "include_in_budget"]
        labels = {
            "name": _("Name"),
            "balance": _("Current balance"),
            "include_in_budget": _("Include in monthly budget"),
        }
        widgets = {
            "balance": forms.NumberInput(attrs={"step": "0.01"}),
        }


class BudgetPreferenceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = BudgetPreference
        fields = ["expected_daily_expense"]
        labels = {"expected_daily_expense": _("Expected spending per day")}
        widgets = {
            "expected_daily_expense": forms.NumberInput(
                attrs={"step": "0.01", "min": "0"}
            )
        }




class PlanningSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = BudgetPreference
        fields = [
            "expected_daily_expense",
            "emergency_buffer",
            "forecast_months",
            "show_money_timeline",
        ]
        labels = {
            "expected_daily_expense": _("Daily spending"),
            "emergency_buffer": _("Emergency buffer"),
            "forecast_months": _("Months to show"),
            "show_money_timeline": _("Show money timeline"),
        }
        widgets = {
            "expected_daily_expense": forms.NumberInput(
                attrs={"step": "0.01", "min": "0"}
            ),
            "emergency_buffer": forms.NumberInput(
                attrs={"step": "0.01", "min": "0"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["forecast_months"].choices = [
            (0, _("Current month")),
            (1, _("1 month ahead")),
            (2, _("2 months ahead")),
            (3, _("3 months ahead")),
        ]

class DashboardAnimationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = BudgetPreference
        fields = [
            "theme",
            "currency",
            "language",
            "transaction_deletion_mode",
            "profile_picture",
            "healthy_gif",
            "warning_gif",
            "danger_gif",
        ]
        labels = {
            "theme": _("Color theme"),
            "currency": _("Display currency"),
            "language": _("Language"),
            "transaction_deletion_mode": _("When deleting a transaction"),
            "profile_picture": _("Profile picture"),
            "healthy_gif": _("On track GIF"),
            "warning_gif": _("Warning GIF"),
            "danger_gif": _("Out of budget GIF"),
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
        self.fields["language"].required = False
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

    def clean_language(self):
        return self.cleaned_data.get("language") or self.instance.language or "en"

    def clean_transaction_deletion_mode(self):
        return (
            self.cleaned_data.get("transaction_deletion_mode")
            or self.instance.transaction_deletion_mode
            or BudgetPreference.DELETE_BALANCE_AUTOMATIC
        )


class SecuritySettingsForm(StyledFormMixin, forms.ModelForm):
    new_pin = forms.RegexField(
        regex=r"^\d{4,8}$",
        required=False,
        label=_("New Darith PIN"),
        error_messages={"invalid": _("Use 4 to 8 digits.")},
        widget=forms.PasswordInput(
            attrs={"inputmode": "numeric", "autocomplete": "new-password"}
        ),
    )
    confirm_pin = forms.CharField(
        required=False,
        label=_("Confirm PIN"),
        widget=forms.PasswordInput(
            attrs={"inputmode": "numeric", "autocomplete": "new-password"}
        ),
    )

    class Meta:
        model = BudgetPreference
        fields = ["lock_timeout_minutes"]
        labels = {"lock_timeout_minutes": _("Lock after")}

    def clean(self):
        cleaned_data = super().clean()
        new_pin = cleaned_data.get("new_pin")
        confirm_pin = cleaned_data.get("confirm_pin")
        if new_pin != confirm_pin:
            self.add_error("confirm_pin", _("The PINs do not match."))
        lock_minutes = cleaned_data.get("lock_timeout_minutes") or 0
        has_unlock_method = bool(
            new_pin
            or self.instance.darith_pin_hash
            or self.instance.user.passkey_credentials.exists()
        )
        if lock_minutes and not has_unlock_method:
            self.add_error(
                "lock_timeout_minutes",
                _("Add a Darith PIN or passkey before enabling inactivity lock."),
            )
        return cleaned_data

    def save(self, commit=True):
        preference = super().save(commit=False)
        if self.cleaned_data.get("new_pin"):
            preference.darith_pin_hash = make_password(self.cleaned_data["new_pin"])
        if commit:
            preference.save()
        return preference


class UsernameChangeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["username"]
        labels = {"username": _("Username")}

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if (
            User.objects.filter(username__iexact=username)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError(_("That username is already in use."))
        return username


class UserPasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = _("Current password")
        self.fields["new_password1"].label = _("New password")
        self.fields["new_password2"].label = _("Confirm new password")


class AccountDeletionForm(StyledFormMixin, forms.Form):
    confirm_deletion = forms.BooleanField(
        label=_("I understand that this permanently deletes my Darith account and live data.")
    )
    signature = forms.CharField(
        max_length=170,
        label=_("Deletion signature"),
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )
    current_password = forms.CharField(
        label=_("Current password"),
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.expected_signature = f"DELETE {user.username}"

    def clean_signature(self):
        signature = self.cleaned_data["signature"]
        if signature != self.expected_signature:
            raise forms.ValidationError(
                _("Type %(signature)s exactly to confirm deletion.")
                % {"signature": self.expected_signature}
            )
        return signature

    def clean_current_password(self):
        password = self.cleaned_data["current_password"]
        if not self.user.check_password(password):
            raise forms.ValidationError(_("Your current password is incorrect."))
        return password


class FeedbackForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = UserFeedback
        fields = ["message"]
        labels = {"message": _("Your feedback")}
        widgets = {
            "message": forms.Textarea(
                attrs={"rows": 5, "placeholder": _("Tell us what worked or what needs attention.")}
            )
        }


class TransactionForm(UserScopedFormMixin, StyledFormMixin, forms.ModelForm):
    def clean_date(self):
        value = self.cleaned_data["date"]
        if value > timezone.localdate():
            raise forms.ValidationError(_("Use a plan for future transactions."))
        return value

    def clean_bank_account(self):
        value = self.cleaned_data.get("bank_account")
        if value is None:
            raise forms.ValidationError(_("Choose a bank account."))
        return value


class ExpenseForm(TransactionForm):
    class Meta:
        model = Expense
        fields = ["text", "amount", "date", "category", "bank_account"]
        labels = {
            "text": _("Description"),
            "amount": _("Amount"),
            "date": _("Date"),
            "category": _("Category"),
            "bank_account": _("Bank account"),
        }
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "date": forms.DateInput(attrs={"type": "date"}),
        }


class IncomeForm(TransactionForm):
    class Meta:
        model = Income
        fields = ["text", "amount", "date", "category", "bank_account"]
        labels = {
            "text": _("Description"),
            "amount": _("Amount"),
            "date": _("Date"),
            "category": _("Category"),
            "bank_account": _("Bank account"),
        }
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "date": forms.DateInput(attrs={"type": "date"}),
        }


class DateRangeForm(UserScopedFormMixin, StyledFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "frequency" in self.fields:
            self.fields["frequency"].required = False
            self.fields["frequency"].initial = self.instance.frequency or "monthly"

    def clean_frequency(self):
        return self.cleaned_data.get("frequency") or "monthly"

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", _("End date must be on or after the first date."))
        if cleaned_data.get("frequency") == "once":
            cleaned_data["end_date"] = None
        return cleaned_data


class RecurringIncomeForm(DateRangeForm):
    class Meta:
        model = RecurringIncome
        fields = ["name", "amount", "frequency", "start_date", "end_date", "category", "bank_account"]
        labels = {
            "name": _("Name"),
            "amount": _("Amount"),
            "frequency": _("Repeat"),
            "start_date": _("First payment date"),
            "end_date": _("Stop repeating after (optional)"),
            "category": _("Category"),
            "bank_account": _("Bank account"),
        }
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class MonthlyExpenseForm(DateRangeForm):
    class Meta:
        model = MonthlyExpense
        fields = ["name", "amount", "frequency", "start_date", "end_date", "category", "bank_account"]
        labels = {
            "name": _("Name"),
            "amount": _("Amount"),
            "frequency": _("Repeat"),
            "start_date": _("First charge date"),
            "end_date": _("Stop repeating after (optional)"),
            "category": _("Category"),
            "bank_account": _("Bank account"),
        }
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class PlanOccurrenceForm(StyledFormMixin, forms.Form):
    amount = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        label=_("Amount"),
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
    )
    date = forms.DateField(
        label=_("Date"), widget=forms.DateInput(attrs={"type": "date"})
    )

    def __init__(self, *args, today=None, allow_past=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.today = today or timezone.localdate()
        self.allow_past = allow_past

    def clean_date(self):
        value = self.cleaned_data["date"]
        if not self.allow_past and value < self.today:
            raise forms.ValidationError(_("Choose today or a future date."))
        return value


class SpendingCheckForm(UserScopedFormMixin, StyledFormMixin, forms.Form):
    amount = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        label=_("Extra amount"),
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
    )
    days = forms.IntegerField(
        min_value=1,
        max_value=365,
        initial=30,
        label=_("Days to spread it over"),
        widget=forms.NumberInput(attrs={"min": "1", "max": "365"}),
    )
    name = forms.CharField(
        max_length=100, required=False, label=_("Name"), initial=_("Extra spending")
    )
    bank_account = forms.ModelChoiceField(
        queryset=BankAccount.objects.none(), label=_("Bank account")
    )


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
            "name": _("Name"),
            "monthly_amount": _("Monthly amount (for an ongoing goal)"),
            "target_amount": _("Target amount (for a dated goal)"),
            "target_date": _("Target date"),
            "current_balance": _("Already saved"),
            "start_date": _("First monthly saving date"),
            "bank_account": _("Default funding account"),
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
                _("Enter both a target amount and target date, or leave both empty."),
            )
        if not target_amount and not monthly_amount:
            self.add_error(
                "monthly_amount",
                _("Enter a monthly amount or define a dated target."),
            )
        if start_date and target_date and target_date < start_date:
            self.add_error("target_date", _("Target date must be on or after the start date."))
        if target_amount and current_balance > target_amount:
            self.add_error("current_balance", _("Saved amount cannot exceed the target."))
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
    source = forms.ChoiceField(label=_("Source"))
    destination = forms.ChoiceField(label=_("Destination"))

    class Meta:
        model = Transfer
        fields = ["name", "amount", "date"]
        labels = {
            "name": _("Description"),
            "amount": _("Amount"),
            "date": _("Date"),
        }
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_destination_goal_id = self.instance.destination_goal_id
        self.order_fields(["name", "amount", "date", "source", "destination"])
        choices = [("", _("Choose an account"))]
        choices.extend(
            (f"bank:{item.pk}", _("Bank - %(name)s") % {"name": item.name})
            for item in BankAccount.objects.filter(user=self.user)
        )
        choices.extend(
            (f"goal:{item.pk}", _("Goal - %(name)s") % {"name": item.name})
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
            raise forms.ValidationError(_("A manual transfer cannot be dated in the future."))
        return value

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("source") == cleaned_data.get("destination"):
            self.add_error("destination", _("Source and destination must be different."))
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
    name = forms.CharField(max_length=50, label=_("Name"))


class RegistrationForm(StyledFormMixin, UserCreationForm):
    email = forms.EmailField(label=_("Email"))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["username", "email", "password1", "password2"]

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("An account with this email already exists."))
        return email
