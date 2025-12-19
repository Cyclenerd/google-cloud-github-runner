"""Integration tests for the Flask application."""
import json
import base64
from unittest.mock import patch


def make_basic_auth_headers(username='cloud', password='test-project'):
    """Create HTTP Basic Auth headers."""
    credentials = base64.b64encode(f'{username}:{password}'.encode()).decode()
    return {'Authorization': f'Basic {credentials}'}


class TestIntegrationWorkflow:
    """Test complete workflow integration."""

    def test_health_check(self, client, monkeypatch):
        """Test that the app is running."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        # Setup route should be accessible
        response = client.get('/setup/', headers=make_basic_auth_headers())
        assert response.status_code == 200

    @patch('app.services.github_service.requests.post')
    @patch('app.services.config_service.ConfigService.store_github_app_id')
    @patch('app.services.config_service.ConfigService.store_github_private_key')
    @patch('app.services.config_service.ConfigService.store_github_webhook_secret')
    def test_full_setup_flow(self, mock_store_secret, mock_store_key, mock_store_app_id, mock_requests, client, monkeypatch):
        """Test complete setup flow from manifest to callback."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        from unittest.mock import MagicMock

        # Mock GitHub API response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'id': 12345,
            'pem': 'FAKE_PEM_KEY',
            'slug': 'test-runner-app',
            'webhook_secret': 'FAKE_WEBHOOK_SECRET',
            'html_url': 'https://github.com/apps/test-runner-app'
        }
        mock_requests.return_value = mock_response
        mock_store_app_id.return_value = True
        mock_store_key.return_value = True

        # Step 1: Get setup page
        response = client.get('/setup/', headers=make_basic_auth_headers())
        assert response.status_code == 200

        # Step 2: Complete callback
        response = client.get('/setup/callback?code=test-code', headers=make_basic_auth_headers())
        assert response.status_code in [200, 302]

    @patch('app.routes.webhook.verify_github_signature')
    @patch('app.services.webhook_service.GitHubClient')
    @patch('app.services.webhook_service.GCloudClient')
    def test_full_webhook_flow(self, mock_gcloud, mock_github, mock_verify, client):
        """Test complete webhook flow."""
        from unittest.mock import Mock

        # Mock signature verification
        mock_verify.return_value = True

        # Setup mocks
        mock_gh_instance = Mock()
        mock_gh_instance.get_registration_token.return_value = "test-token"
        mock_github.return_value = mock_gh_instance

        mock_gc_instance = Mock()
        mock_gc_instance.create_runner_instance.return_value = "runner-test"
        mock_gcloud.return_value = mock_gc_instance

        # Send workflow_job webhook
        payload = {
            'action': 'queued',
            'workflow_job': {
                'id': 123,
                'labels': ['gcp-ubuntu-24.04']
            },
            'repository': {
                'html_url': 'https://github.com/owner/repo',
                'full_name': 'owner/repo'
            }
        }

        response = client.post(
            '/webhook',
            data=json.dumps(payload),
            content_type='application/json',
            headers={'X-GitHub-Event': 'workflow_job'}
        )

        assert response.status_code == 200
        assert response.json['status'] == 'success'
        mock_gh_instance.get_registration_token.assert_called_once()
        mock_gc_instance.create_runner_instance.assert_called_once()
