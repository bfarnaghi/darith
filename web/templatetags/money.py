# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from decimal import Decimal, InvalidOperation

from django import template

from web.models import BudgetPreference


register = template.Library()
MASKED_AMOUNT = "******"


def _format_money(value, preference, forced_sign=""):
    if preference and preference.hide_financial_values:
        return MASKED_AMOUNT

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value

    symbol = (
        preference.currency_symbol
        if preference
        else BudgetPreference.CURRENCY_SYMBOLS[BudgetPreference.CURRENCY_EUR]
    )
    sign = forced_sign
    if not forced_sign and amount < 0:
        sign = "−"
    return f"{sign}{symbol}{abs(amount):,.2f}"


@register.filter
def money(value, preference):
    return _format_money(value, preference)


@register.filter
def money_plus(value, preference):
    return _format_money(value, preference, "+")


@register.filter
def money_minus(value, preference):
    return _format_money(value, preference, "−")
