# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from urllib.parse import urlencode
import time

from django.conf import settings
from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse

from .subscriptions import user_has_subscription_access
from .models import BudgetPreference
from .security import LAST_ACTIVITY_SESSION_KEY, LOCKED_SESSION_KEY


EXEMPT_URL_NAMES = {
    "create_account",
    "forgot_password",
    "home",
    "login",
    "logout",
    "pricing",
    "reset_password",
    "subscription_overview",
    "report_subscription_payment",
    "tutorial",
}


class SubscriptionAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._requires_subscription(request):
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('subscription_overview')}?{query}")
        return self.get_response(request)

    def _requires_subscription(self, request):
        if not settings.SUBSCRIPTIONS_ENABLED or not request.user.is_authenticated:
            return False
        if request.user.is_staff or request.user.is_superuser:
            return False
        static_prefix = f"/{settings.STATIC_URL.lstrip('/')}"
        if request.path_info.startswith(("/admin/", static_prefix)):
            return False
        try:
            url_name = resolve(request.path_info).url_name
        except Resolver404:
            return False
        if url_name in EXEMPT_URL_NAMES:
            return False
        return not user_has_subscription_access(request.user)


LOCK_EXEMPT_URL_NAMES = {
    "create_account",
    "forgot_password",
    "home",
    "login",
    "logout",
    "passkey_login_options",
    "passkey_login_verify",
    "passkey_unlock_options",
    "passkey_unlock_verify",
    "pricing",
    "reset_password",
    "security_activity",
    "security_lock",
    "security_unlock",
    "session_locked",
    "tutorial",
}


class SessionLockMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        redirect_response = self._lock_redirect(request)
        if redirect_response:
            return redirect_response
        return self.get_response(request)

    def _lock_redirect(self, request):
        if not request.user.is_authenticated:
            return None
        static_prefix = f"/{settings.STATIC_URL.lstrip('/')}"
        if request.path_info.startswith(("/admin/", static_prefix)):
            return None
        try:
            url_name = resolve(request.path_info).url_name
        except Resolver404:
            return None
        if url_name in LOCK_EXEMPT_URL_NAMES:
            return None

        preference, _ = BudgetPreference.objects.get_or_create(user=request.user)
        timeout_minutes = preference.lock_timeout_minutes
        if not timeout_minutes:
            request.session.pop(LOCKED_SESSION_KEY, None)
            request.session.pop(LAST_ACTIVITY_SESSION_KEY, None)
            return None

        now = time.time()
        last_activity = request.session.get(LAST_ACTIVITY_SESSION_KEY)
        expired = bool(
            last_activity
            and now - float(last_activity) >= timeout_minutes * 60
        )
        if request.session.get(LOCKED_SESSION_KEY) or expired:
            request.session[LOCKED_SESSION_KEY] = True
            return redirect("session_locked")

        request.session[LAST_ACTIVITY_SESSION_KEY] = now
        return None
