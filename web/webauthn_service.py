# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import base64
from urllib.parse import urlsplit

from django.conf import settings
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .models import PasskeyCredential


REGISTRATION_CHALLENGE_KEY = "darith_passkey_registration_challenge"
AUTHENTICATION_CHALLENGE_KEY = "darith_passkey_authentication_challenge"


def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value):
    return base64url_to_bytes(value)


def _transport_values(values):
    transports = []
    for value in values:
        try:
            transports.append(AuthenticatorTransport(value))
        except ValueError:
            continue
    return transports


def relying_party(request):
    host = urlsplit(f"//{request.get_host()}").hostname or request.get_host()
    rp_id = settings.WEBAUTHN_RP_ID or host
    origin = settings.WEBAUTHN_ORIGIN or f"{request.scheme}://{request.get_host()}"
    return rp_id, origin


def registration_options(request):
    credentials = request.user.passkey_credentials.all()
    rp_id, _ = relying_party(request)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=str(request.user.pk).encode("ascii"),
        user_name=request.user.username,
        user_display_name=request.user.get_full_name() or request.user.username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=bytes(item.credential_id))
            for item in credentials
        ],
    )
    request.session[REGISTRATION_CHALLENGE_KEY] = _encode(options.challenge)
    return options_to_json(options)


def verify_registration(request, credential):
    encoded_challenge = request.session.pop(REGISTRATION_CHALLENGE_KEY, None)
    if not encoded_challenge:
        raise ValueError("The passkey setup request expired. Please try again.")
    rp_id, origin = relying_party(request)
    return verify_registration_response(
        credential=credential,
        expected_challenge=_decode(encoded_challenge),
        expected_rp_id=rp_id,
        expected_origin=origin,
        require_user_verification=True,
    )


def authentication_options(request, user=None):
    rp_id, _ = relying_party(request)
    credentials = user.passkey_credentials.all() if user else PasskeyCredential.objects.none()
    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=(
            [
                PublicKeyCredentialDescriptor(
                    id=bytes(item.credential_id),
                    transports=_transport_values(item.transports),
                )
                for item in credentials
            ]
            if user
            else None
        ),
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    request.session[AUTHENTICATION_CHALLENGE_KEY] = _encode(options.challenge)
    return options_to_json(options)


def credential_from_response(payload, user=None):
    credential_id = _decode(payload.get("id", ""))
    credentials = PasskeyCredential.objects.select_related("user")
    if user:
        credentials = credentials.filter(user=user)
    return credentials.get(credential_id=credential_id)


def verify_authentication(request, payload, credential):
    encoded_challenge = request.session.pop(AUTHENTICATION_CHALLENGE_KEY, None)
    if not encoded_challenge:
        raise ValueError("The passkey request expired. Please try again.")
    rp_id, origin = relying_party(request)
    return verify_authentication_response(
        credential=payload,
        expected_challenge=_decode(encoded_challenge),
        expected_rp_id=rp_id,
        expected_origin=origin,
        credential_public_key=bytes(credential.public_key),
        credential_current_sign_count=credential.sign_count,
        require_user_verification=True,
    )
