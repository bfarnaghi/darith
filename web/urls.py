# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("login/", views.user_login, name="login"),
    path("logout/", views.user_logout, name="logout"),
    path("create-account/", views.create_account, name="create_account"),
    path("forgot-password/", views.forgot_password, name="forgot_password"),
    path("reset-password/<str:uidb64>/<str:token>/", views.reset_password, name="reset_password"),
    path("accounts/create/", views.create_bank_account, name="create_bank_account"),
    path("accounts/<int:account_id>/update/", views.update_bank_account, name="update_bank_account"),
    path("accounts/<int:account_id>/delete/", views.delete_bank_account, name="delete_bank_account"),
    path("expenses/create/", views.create_expense, name="create_expense"),
    path("expenses/<int:expense_id>/update/", views.update_expense, name="update_expense"),
    path("expenses/<int:expense_id>/delete/", views.delete_expense, name="delete_expense"),
    path("incomes/create/", views.create_income, name="create_income"),
    path("incomes/<int:income_id>/update/", views.update_income, name="update_income"),
    path("incomes/<int:income_id>/delete/", views.delete_income, name="delete_income"),
    path("plans/income/create/", views.create_recurring_income, name="create_recurring_income"),
    path("plans/income/<int:item_id>/update/", views.update_recurring_income, name="update_recurring_income"),
    path("plans/income/<int:item_id>/delete/", views.delete_recurring_income, name="delete_recurring_income"),
    path("plans/expense/create/", views.create_monthly_expense, name="create_monthly_expense"),
    path("plans/expense/<int:item_id>/update/", views.update_monthly_expense, name="update_monthly_expense"),
    path("plans/expense/<int:item_id>/delete/", views.delete_monthly_expense, name="delete_monthly_expense"),
    path("plans/saving/create/", views.create_savings_goal, name="create_savings_goal"),
    path("plans/saving/<int:item_id>/update/", views.update_savings_goal, name="update_savings_goal"),
    path("plans/saving/<int:item_id>/delete/", views.delete_savings_goal, name="delete_savings_goal"),
    path("categories/<str:kind>/create/", views.create_category, name="create_category"),
    path("categories/<str:kind>/<int:item_id>/update/", views.update_category, name="update_category"),
    path("categories/<str:kind>/<int:item_id>/delete/", views.delete_category, name="delete_category"),
]
