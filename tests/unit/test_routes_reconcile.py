"""
Tests for the /reconcile route: OIDC authentication, locking and the report response.
"""
from unittest.mock import patch

import pytest

from app.routes import reconcile as reconcile_module
from app.utils.security import verify_google_oidc_token

AUD = 'https://github-runners-manager-uc1-123.us-central1.run.app'
INVOKER = 'github-runners-reconciler@proj.iam.gserviceaccount.com'


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('RECONCILE_AUDIENCE', AUD)
    monkeypatch.setenv('RECONCILE_INVOKER_EMAIL', INVOKER)


def _claims(email=INVOKER, verified=True):
    return {'aud': AUD, 'iss': 'https://accounts.google.com', 'email': email, 'email_verified': verified}


class TestVerifyGoogleOidcToken:
    def test_unconfigured_is_rejected(self):
        claims, reason = verify_google_oidc_token('Bearer x', None, [INVOKER])
        assert claims is None and 'not configured' in reason
        claims, reason = verify_google_oidc_token('Bearer x', AUD, [''])
        assert claims is None and 'not configured' in reason

    def test_missing_bearer(self):
        claims, reason = verify_google_oidc_token(None, AUD, [INVOKER])
        assert claims is None and 'missing bearer' in reason
        claims, reason = verify_google_oidc_token('Basic abc', AUD, [INVOKER])
        assert claims is None

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_invalid_token(self, verify):
        verify.side_effect = ValueError('Token expired')
        claims, reason = verify_google_oidc_token('Bearer bad', AUD, [INVOKER])
        assert claims is None and 'Token expired' in reason

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_wrong_caller(self, verify):
        verify.return_value = _claims(email='someone-else@proj.iam.gserviceaccount.com')
        claims, reason = verify_google_oidc_token('Bearer t', AUD, [INVOKER])
        assert claims is None and 'not allowed' in reason

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_unverified_email(self, verify):
        verify.return_value = _claims(verified=False)
        claims, _ = verify_google_oidc_token('Bearer t', AUD, [INVOKER])
        assert claims is None

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_valid_token_checks_audience(self, verify):
        verify.return_value = _claims(email=INVOKER.upper())
        claims, reason = verify_google_oidc_token('Bearer t', AUD, [INVOKER])
        assert claims is not None and reason == ''
        assert verify.call_args.kwargs['audience'] == AUD
        assert verify.call_args.kwargs['clock_skew_in_seconds'] == 10


class TestReconcileRoute:
    def test_unconfigured_returns_503(self, client, monkeypatch):
        monkeypatch.delenv('RECONCILE_AUDIENCE', raising=False)
        monkeypatch.delenv('RECONCILE_INVOKER_EMAIL', raising=False)
        response = client.post('/reconcile', headers={'Authorization': 'Bearer t'})
        assert response.status_code == 503

    def test_missing_token_returns_403(self, client, configured):
        response = client.post('/reconcile')
        assert response.status_code == 403

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_wrong_caller_returns_403(self, verify, client, configured):
        verify.return_value = _claims(email='intruder@example.com')
        response = client.post('/reconcile', headers={'Authorization': 'Bearer t'})
        assert response.status_code == 403

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_get_is_not_allowed(self, verify, client, configured):
        response = client.get('/reconcile')
        assert response.status_code == 405

    @patch('app.routes.reconcile.ReconcileService')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_valid_call_runs_a_pass_and_returns_report(self, verify, service_class, client, configured):
        verify.return_value = _claims()
        service_class.return_value.run.return_value = {'run_id': 'r1', 'deleted': [], 'created': [{'job_id': '1'}]}
        response = client.post('/reconcile?dry_run=1', headers={'Authorization': 'Bearer t'})
        assert response.status_code == 200
        assert response.get_json()['status'] == 'success'
        assert response.get_json()['created'] == [{'job_id': '1'}]
        service_class.return_value.run.assert_called_once_with(dry_run=True)

    @patch('app.routes.reconcile.ReconcileService')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_pass_failure_returns_500(self, verify, service_class, client, configured):
        verify.return_value = _claims()
        service_class.return_value.run.side_effect = RuntimeError('github down')
        response = client.post('/reconcile', headers={'Authorization': 'Bearer t'})
        assert response.status_code == 500
        assert 'github down' not in response.get_data(as_text=True)

    @patch('app.routes.reconcile.ReconcileService')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_concurrent_pass_returns_409(self, verify, service_class, client, configured):
        verify.return_value = _claims()
        assert reconcile_module._reconcile_lock.acquire(blocking=False)
        try:
            response = client.post('/reconcile', headers={'Authorization': 'Bearer t'})
        finally:
            reconcile_module._reconcile_lock.release()
        assert response.status_code == 409
        service_class.return_value.run.assert_not_called()
