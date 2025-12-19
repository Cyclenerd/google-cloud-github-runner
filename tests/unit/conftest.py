import pytest
from unittest.mock import Mock, patch
from app import create_app


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Set up test environment variables."""
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')


@pytest.fixture
def app():
    """Create and configure a test app instance."""
    app = create_app()
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """Create a test client for the app."""
    return app.test_client()


@pytest.fixture
def mock_github_client():
    """Mock GitHubClient for testing."""
    with patch('app.clients.github_client.GitHubClient') as mock:
        instance = Mock()
        instance.get_registration_token.return_value = "fake-token-12345"
        instance.get_installation_access_token.return_value = "fake-install-token"
        mock.return_value = instance
        yield instance


@pytest.fixture
def mock_gcloud_client():
    """Mock GCloudClient for testing."""
    with patch('app.clients.gcloud_client.GCloudClient') as mock:
        instance = Mock()
        instance.create_runner_instance.return_value = "runner-fake123"
        instance.delete_runner_instance.return_value = None
        mock.return_value = instance
        yield instance


@pytest.fixture
def mock_config_service():
    """Mock ConfigService for testing."""
    with patch('app.services.config_service.ConfigService') as mock:
        instance = Mock()
        instance.store_github_app_id.return_value = True
        instance.store_github_private_key.return_value = True
        instance.store_github_installation_id.return_value = True
        instance.store_github_webhook_secret.return_value = True
        mock.return_value = instance
        yield instance


@pytest.fixture
def mock_requests():
    """Mock requests library."""
    with patch('app.services.github_service.requests') as mock:
        yield mock


@pytest.fixture
def sample_workflow_job_payload():
    """Sample workflow_job webhook payload."""
    return {
        'action': 'queued',
        'workflow_job': {
            'id': 123456,
            'labels': ['gcp-ubuntu-24.04', 'linux'],
            'runner_name': None
        },
        'repository': {
            'html_url': 'https://github.com/owner/repo',
            'full_name': 'owner/repo'
        }
    }


@pytest.fixture
def sample_installation_payload():
    """Sample installation webhook payload."""
    return {
        'action': 'created',
        'installation': {
            'id': 987654,
            'account': {
                'login': 'test-org'
            }
        }
    }
