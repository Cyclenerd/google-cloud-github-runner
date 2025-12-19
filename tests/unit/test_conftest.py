"""Tests for conftest.py fixtures to ensure they work correctly."""


class TestFixtures:
    def test_app_fixture(self, app):
        """Test that app fixture creates a Flask app with TESTING enabled."""
        assert app is not None
        assert app.config['TESTING'] is True

    def test_client_fixture(self, client):
        """Test that client fixture creates a test client."""
        assert client is not None
        # Test that we can make a request
        response = client.get('/')
        assert response is not None

    def test_mock_github_client_fixture(self, mock_github_client):
        """Test that mock_github_client fixture returns correct values."""
        assert mock_github_client is not None
        assert mock_github_client.get_registration_token.return_value == "fake-token-12345"
        assert mock_github_client.get_installation_access_token.return_value == "fake-install-token"

    def test_mock_gcloud_client_fixture(self, mock_gcloud_client):
        """Test that mock_gcloud_client fixture returns correct values."""
        assert mock_gcloud_client is not None
        assert mock_gcloud_client.create_runner_instance.return_value == "runner-fake123"
        assert mock_gcloud_client.delete_runner_instance.return_value is None

    def test_mock_config_service_fixture(self, mock_config_service):
        """Test that mock_config_service fixture returns correct values."""
        assert mock_config_service is not None
        assert mock_config_service.store_github_app_id.return_value is True
        assert mock_config_service.store_github_private_key.return_value is True
        assert mock_config_service.store_github_installation_id.return_value is True
        assert mock_config_service.store_github_webhook_secret.return_value is True

    def test_mock_requests_fixture(self, mock_requests):
        """Test that mock_requests fixture is available."""
        assert mock_requests is not None

    def test_sample_workflow_job_payload_fixture(self, sample_workflow_job_payload):
        """Test that sample_workflow_job_payload fixture has correct structure."""
        assert sample_workflow_job_payload is not None
        assert sample_workflow_job_payload['action'] == 'queued'
        assert sample_workflow_job_payload['workflow_job']['id'] == 123456
        assert 'gcp-ubuntu-24.04' in sample_workflow_job_payload['workflow_job']['labels']
        assert sample_workflow_job_payload['repository']['full_name'] == 'owner/repo'

    def test_sample_installation_payload_fixture(self, sample_installation_payload):
        """Test that sample_installation_payload fixture has correct structure."""
        assert sample_installation_payload is not None
        assert sample_installation_payload['action'] == 'created'
        assert sample_installation_payload['installation']['id'] == 987654
        assert sample_installation_payload['installation']['account']['login'] == 'test-org'
