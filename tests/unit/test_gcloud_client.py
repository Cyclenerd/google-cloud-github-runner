import pytest
from unittest.mock import patch, MagicMock
from app.clients.gcloud_client import GCloudClient


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set up mock environment variables for GCloud client."""
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
    monkeypatch.setenv('GOOGLE_CLOUD_ZONE', 'us-central1-a')


@pytest.fixture
def mock_instance_client():
    """Mock the Compute Engine instance client."""
    with patch('app.clients.gcloud_client.compute_v1.InstancesClient') as mock:
        yield mock


class TestGCloudClient:
    def test_init_with_env_vars(self, mock_env_vars, mock_instance_client):
        """Test GCloudClient initialization with environment variables."""
        client = GCloudClient()

        assert client.project_id == 'test-project'
        assert client.zone == 'us-central1-a'
        assert client.region == 'us-central1'

    def test_init_default_zone(self, monkeypatch, mock_instance_client):
        """Test GCloudClient initialization with default zone."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        monkeypatch.delenv('GOOGLE_CLOUD_ZONE', raising=False)

        client = GCloudClient()

        assert client.zone == 'us-central1-a'
        assert client.region == 'us-central1'

    def test_init_missing_project_id(self, mock_instance_client):
        """Test GCloudClient initialization with missing project ID."""
        with patch.dict('os.environ', {}, clear=True):
            client = GCloudClient()
            assert client.project_id is None

    @patch('app.clients.gcloud_client.compute_v1')
    def test_create_runner_instance(self, mock_compute, mock_env_vars):
        """Test creating a runner instance."""
        mock_instance_client = MagicMock()
        mock_operation = MagicMock()
        mock_operation.name = 'operation-123'
        mock_instance_client.insert.return_value = mock_operation
        mock_compute.InstancesClient.return_value = mock_instance_client

        # Mock RegionInstanceTemplatesClient
        mock_templates_client = MagicMock()
        mock_template = MagicMock()
        mock_template.name = 'gcp-ubuntu-24-04-12345678901234'
        mock_template.self_link = ('https://www.googleapis.com/compute/v1/projects/test-project/regions/us-central1/'
                                   'instanceTemplates/gcp-ubuntu-24-04-12345678901234')
        mock_templates_client.list.return_value = [mock_template]
        mock_compute.RegionInstanceTemplatesClient.return_value = mock_templates_client

        client = GCloudClient()
        instance_name = client.create_runner_instance(
            'fake-token-12345678',
            'https://github.com/owner/repo',
            'gcp-ubuntu-24.04'
        )

        assert instance_name.startswith('runner-')
        mock_instance_client.insert.assert_called_once()

    @patch('app.clients.gcloud_client.compute_v1')
    def test_create_runner_instance_error(self, mock_compute, mock_env_vars):
        """Test error handling when creating instance fails."""
        mock_instance_client = MagicMock()
        mock_instance_client.insert.side_effect = Exception("API Error")
        mock_compute.InstancesClient.return_value = mock_instance_client

        # Mock RegionInstanceTemplatesClient
        mock_templates_client = MagicMock()
        mock_template = MagicMock()
        mock_template.name = 'gcp-ubuntu-24-04-12345678901234'
        mock_template.self_link = ('https://www.googleapis.com/compute/v1/projects/test-project/regions/us-central1/'
                                   'instanceTemplates/gcp-ubuntu-24-04-12345678901234')
        mock_templates_client.list.return_value = [mock_template]
        mock_compute.RegionInstanceTemplatesClient.return_value = mock_templates_client

        client = GCloudClient()

        with pytest.raises(Exception, match="API Error"):
            client.create_runner_instance(
                'fake-token',
                'https://github.com/owner/repo',
                'gcp-ubuntu-24.04'
            )

    @patch('app.clients.gcloud_client.compute_v1')
    def test_delete_runner_instance(self, mock_compute, mock_env_vars):
        """Test deleting a runner instance."""
        mock_instance_client = MagicMock()
        mock_operation = MagicMock()
        mock_operation.name = 'delete-operation-123'
        mock_instance_client.delete.return_value = mock_operation
        mock_compute.InstancesClient.return_value = mock_instance_client

        client = GCloudClient()
        client.delete_runner_instance('runner-12345')

        mock_instance_client.delete.assert_called_once_with(
            project='test-project',
            zone='us-central1-a',
            instance='runner-12345'
        )

    @patch('app.clients.gcloud_client.compute_v1')
    def test_delete_runner_instance_error(self, mock_compute, mock_env_vars):
        """Test error handling when deleting instance fails."""
        mock_instance_client = MagicMock()
        mock_instance_client.delete.side_effect = Exception("Delete Error")
        mock_compute.InstancesClient.return_value = mock_instance_client

        client = GCloudClient()

        with pytest.raises(Exception, match="Delete Error"):
            client.delete_runner_instance('runner-12345')

    @patch('app.clients.gcloud_client.compute_v1')
    def test_get_template_name_found(self, mock_compute, mock_env_vars):
        """Test finding a template by prefix."""
        mock_templates_client = MagicMock()
        mock_template1 = MagicMock()
        mock_template1.name = 'other-template'
        mock_template2 = MagicMock()
        mock_template2.name = 'gcp-target-template-123456789012345'

        mock_templates_client.list.return_value = [mock_template1, mock_template2]
        mock_compute.RegionInstanceTemplatesClient.return_value = mock_templates_client

        client = GCloudClient()
        result = client._get_template_name('gcp-target-template')

        assert result.name == 'gcp-target-template-123456789012345'

    @patch('app.clients.gcloud_client.compute_v1')
    def test_get_template_name_not_found(self, mock_compute, mock_env_vars):
        """Test not finding a template."""
        mock_templates_client = MagicMock()
        mock_template = MagicMock()
        mock_template.name = 'other-template'

        mock_templates_client.list.return_value = [mock_template]
        mock_compute.RegionInstanceTemplatesClient.return_value = mock_templates_client

        client = GCloudClient()
        result = client._get_template_name('non-existent')

        assert result is None

    @patch('app.clients.gcloud_client.compute_v1')
    def test_get_template_name_exception(self, mock_compute, mock_env_vars):
        """Test handling exception when getting template."""
        mock_templates_client = MagicMock()
        mock_templates_client.list.side_effect = Exception("API Error")
        mock_compute.RegionInstanceTemplatesClient.return_value = mock_templates_client

        client = GCloudClient()
        result = client._get_template_name('any-template')

        assert result is None

    @patch('app.clients.gcloud_client.compute_v1')
    def test_create_runner_instance_no_template(self, mock_compute, mock_env_vars):
        """Test creating runner instance when no template is found."""
        mock_templates_client = MagicMock()
        mock_templates_client.list.return_value = []
        mock_compute.RegionInstanceTemplatesClient.return_value = mock_templates_client

        mock_instance_client = MagicMock()
        mock_compute.InstancesClient.return_value = mock_instance_client

        client = GCloudClient()
        result = client.create_runner_instance(
            'fake-token',
            'https://github.com/owner/repo',
            'non-existent-template'
        )

        assert result is None
        mock_instance_client.insert.assert_not_called()
