import os
from unittest.mock import patch
from app.utils.security import verify_github_signature


class TestVerifyGitHubSignature:
    def test_verify_valid_signature(self):
        """Test verification with a valid GitHub signature."""
        payload = b'{"test": "data"}'
        secret = 'my-webhook-secret'

        # Calculate expected signature
        import hmac
        import hashlib
        expected_sig = "sha256=" + hmac.new(
            secret.encode('utf-8'),
            msg=payload,
            digestmod=hashlib.sha256
        ).hexdigest()

        with patch.dict(os.environ, {'GITHUB_WEBHOOK_SECRET': secret}):
            result = verify_github_signature(payload, expected_sig)
            assert result is True

    def test_verify_invalid_signature(self):
        """Test verification with an invalid signature."""
        payload = b'{"test": "data"}'
        secret = 'my-webhook-secret'
        invalid_signature = 'sha256=invalid_signature_value'

        with patch.dict(os.environ, {'GITHUB_WEBHOOK_SECRET': secret}):
            result = verify_github_signature(payload, invalid_signature)
            assert result is False

    def test_verify_no_secret_configured(self):
        """Test verification when webhook secret is not configured."""
        payload = b'{"test": "data"}'
        signature = 'sha256=some_signature'

        with patch.dict(os.environ, {}, clear=True):
            result = verify_github_signature(payload, signature)
            assert result is False

    def test_verify_no_signature_header(self):
        """Test verification when signature header is missing."""
        payload = b'{"test": "data"}'

        with patch.dict(os.environ, {'GITHUB_WEBHOOK_SECRET': 'secret'}):
            result = verify_github_signature(payload, None)
            assert result is False

    def test_verify_empty_signature_header(self):
        """Test verification with empty signature header."""
        payload = b'{"test": "data"}'

        with patch.dict(os.environ, {'GITHUB_WEBHOOK_SECRET': 'secret'}):
            result = verify_github_signature(payload, '')
            assert result is False

    def test_verify_different_payload(self):
        """Test verification fails when payload doesn't match signature."""
        secret = 'my-webhook-secret'
        original_payload = b'{"test": "original"}'
        different_payload = b'{"test": "different"}'

        # Calculate signature for original payload
        import hmac
        import hashlib
        signature = "sha256=" + hmac.new(
            secret.encode('utf-8'),
            msg=original_payload,
            digestmod=hashlib.sha256
        ).hexdigest()

        with patch.dict(os.environ, {'GITHUB_WEBHOOK_SECRET': secret}):
            # Verify with different payload should fail
            result = verify_github_signature(different_payload, signature)
            assert result is False

    def test_verify_timing_attack_resistant(self):
        """Test that signature comparison is timing-attack resistant."""
        payload = b'{"test": "data"}'
        secret = 'my-webhook-secret'

        import hmac
        import hashlib
        correct_sig = "sha256=" + hmac.new(
            secret.encode('utf-8'),
            msg=payload,
            digestmod=hashlib.sha256
        ).hexdigest()

        # Create a signature that differs only in the last character
        almost_correct_sig = correct_sig[:-1] + ('0' if correct_sig[-1] != '0' else '1')

        with patch.dict(os.environ, {'GITHUB_WEBHOOK_SECRET': secret}):
            result = verify_github_signature(payload, almost_correct_sig)
            assert result is False
