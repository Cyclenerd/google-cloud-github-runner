"""
Security utilities for the application.
"""
import hmac
import hashlib
import logging
import os


logger = logging.getLogger(__name__)


def verify_github_signature(payload_body, signature_header):
    """
    Verify that the payload was sent from GitHub by validating SHA256.

    Args:
        payload_body: original request body to verify (bytes)
        signature_header: header received from GitHub (x-hub-signature-256)

    Returns:
        True if the signature is valid, False otherwise
    """
    secret = os.environ.get('GITHUB_WEBHOOK_SECRET')
    if not secret:
        logger.error("GITHUB_WEBHOOK_SECRET not configured")
        return False

    if not signature_header:
        logger.error("No X-Hub-Signature-256 header received")
        return False

    hash_object = hmac.new(
        secret.encode('utf-8'),
        msg=payload_body,
        digestmod=hashlib.sha256
    )
    expected_signature = "sha256=" + hash_object.hexdigest()

    if not hmac.compare_digest(expected_signature, signature_header):
        logger.error("Invalid GitHub signature")
        return False

    return True


def verify_google_oidc_token(authorization_header, audience, allowed_emails):
    """
    Verify a Google-issued OIDC identity token (Cloud Scheduler, Compute VM service accounts).

    Args:
        authorization_header: value of the ``Authorization`` header (``Bearer <jwt>``)
        audience: the exact ``aud`` claim the token must carry
        allowed_emails: iterable of service account emails allowed to call the route

    Returns:
        tuple(dict or None, str): the verified claims and '' on success, else (None, reason).
    """
    allowed = {email.strip().lower() for email in (allowed_emails or []) if email and email.strip()}
    if not audience or not allowed:
        return None, 'route not configured (missing audience or allowed caller)'
    if not authorization_header or not authorization_header.startswith('Bearer '):
        return None, 'missing bearer token'
    token = authorization_header[len('Bearer '):].strip()
    try:
        # Lazy import keeps app start-up independent of google-auth's HTTP transport.
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
        # A few seconds of skew: Google-minted tokens are occasionally rejected as "used too early".
        claims = google_id_token.verify_oauth2_token(token, google_requests.Request(), audience=audience,
                                                     clock_skew_in_seconds=10)
    except Exception as e:
        return None, f'invalid token: {e}'
    email = (claims.get('email') or '').lower()
    if not email or not claims.get('email_verified', False):
        return None, 'token carries no verified email'
    if email not in allowed:
        return None, f'caller {email} is not allowed'
    return claims, ''
