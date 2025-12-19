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
