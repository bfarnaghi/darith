# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse

from .subscriptions import user_has_subscription_access


EXEMPT_URL_NAMES = {
    "create_account",
    "forgot_password",
    "home",
    "login",
    "logout",
    "reset_password",
    "stripe_webhook",
    "subscription_checkout",
    "subscription_overview",
    "subscription_portal",
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
