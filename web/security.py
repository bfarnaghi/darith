# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import time


LOCKED_SESSION_KEY = "darith_locked"
LAST_ACTIVITY_SESSION_KEY = "darith_last_activity"
PIN_ATTEMPTS_SESSION_KEY = "darith_pin_attempts"
PIN_BLOCKED_UNTIL_SESSION_KEY = "darith_pin_blocked_until"


def mark_session_unlocked(request):
    request.session[LOCKED_SESSION_KEY] = False
    request.session[LAST_ACTIVITY_SESSION_KEY] = time.time()
    request.session.pop(PIN_ATTEMPTS_SESSION_KEY, None)
    request.session.pop(PIN_BLOCKED_UNTIL_SESSION_KEY, None)


def mark_session_locked(request):
    request.session[LOCKED_SESSION_KEY] = True


def touch_session(request):
    request.session[LAST_ACTIVITY_SESSION_KEY] = time.time()
