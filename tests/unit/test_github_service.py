import pytest
import json
from unittest.mock import patch, MagicMock
from app.services.github_service import GitHubService


class TestGitHubService:
    def test_generate_manifest(self):
        """Test generating GitHub App manifest."""
        base_url = "https://example.com"
        manifest_json = GitHubService.generate_manifest(base_url)
        manifest = json.loads(manifest_json)

        assert manifest['url'] == base_url
        assert manifest['hook_attributes']['url'] == f"{base_url}/webhook"
        assert manifest['redirect_url'] == f"{base_url}/setup/callback"
        assert manifest['setup_url'] == f"{base_url}/setup/complete"
        assert manifest['hook_attributes']['active'] is True
        assert manifest['default_permissions']['administration'] == 'write'
        assert manifest['default_permissions']['organization_self_hosted_runners'] == 'write'
        assert 'workflow_job' in manifest['default_events']
        assert manifest['public'] is False

    @patch('app.services.github_service.requests.post')
    def test_exchange_code_success(self, mock_post):
        """Test exchanging code for app configuration."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'id': 12345,
            'pem': 'FAKE_PEM_KEY',
            'slug': 'test-app'
        }
        mock_post.return_value = mock_response

        result = GitHubService.exchange_code('test-code-123')

        assert result['id'] == 12345
        assert result['pem'] == 'FAKE_PEM_KEY'
        assert result['slug'] == 'test-app'
        mock_post.assert_called_once_with('https://api.github.com/app-manifests/test-code-123/conversions', timeout=30)

    @patch('app.services.github_service.requests.post')
    def test_exchange_code_error(self, mock_post):
        """Test error handling when exchanging code fails."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("API Error")
        mock_post.return_value = mock_response

        with pytest.raises(Exception, match="API Error"):
            GitHubService.exchange_code('invalid-code')

    def test_get_installation_url(self):
        """Test generating installation URL."""
        url = GitHubService.get_installation_url('my-app')

        assert url == 'https://github.com/apps/my-app/installations/new'
