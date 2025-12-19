from unittest.mock import patch
import base64


def make_basic_auth_headers(username='cloud', password='test-project'):
    """Create HTTP Basic Auth headers."""
    credentials = base64.b64encode(f'{username}:{password}'.encode()).decode()
    return {'Authorization': f'Basic {credentials}'}


class TestSetupRoutes:
    @patch('app.routes.setup.ConfigService')
    def test_setup_page_loads(self, mock_config_service, client, monkeypatch):
        """Test that setup page loads successfully."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        mock_config_instance = mock_config_service.return_value
        mock_config_instance.is_configured.return_value = {
            'is_configured': False,
            'app_id': None,
            'installation_id': None,
            'has_private_key': False
        }

        response = client.get('/setup/', headers=make_basic_auth_headers())

        assert response.status_code == 200
        assert b'manifest' in response.data or b'setup' in response.data.lower()

    @patch('app.routes.setup.GitHubService.get_installation_url')
    @patch('app.routes.setup.GitHubService.exchange_code')
    @patch('app.routes.setup.ConfigService')
    def test_setup_callback_success(self, mock_config_service, mock_exchange, mock_get_installation_url, client, monkeypatch):
        """Test successful setup callback."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        mock_exchange.return_value = {
            'id': 12345,
            'pem': 'FAKE_PEM',
            'slug': 'test-app',
            'webhook_secret': 'FAKE_WEBHOOK_SECRET',
            'html_url': 'https://github.com/apps/test-app'
        }

        mock_get_installation_url.return_value = 'https://github.com/apps/test-app/installations/new'

        mock_config_instance = mock_config_service.return_value
        mock_config_instance.is_configured.return_value = {
            'is_configured': False,
            'app_id': None,
            'installation_id': None,
            'has_private_key': False
        }

        response = client.get('/setup/callback?code=test-code-123', headers=make_basic_auth_headers())

        assert response.status_code == 302
        mock_exchange.assert_called_once_with('test-code-123')
        mock_config_instance.store_github_app_id.assert_called_once_with(12345)
        mock_config_instance.store_github_private_key.assert_called_once_with('FAKE_PEM')

    @patch('app.routes.setup.ConfigService')
    def test_setup_callback_no_code(self, mock_config_service, client, monkeypatch):
        """Test setup callback without code parameter."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        mock_config_instance = mock_config_service.return_value
        mock_config_instance.is_configured.return_value = {
            'is_configured': False,
            'app_id': None,
            'installation_id': None,
            'has_private_key': False
        }

        response = client.get('/setup/callback', headers=make_basic_auth_headers())

        assert response.status_code == 400
        assert b'No code provided' in response.data

    @patch('app.routes.setup.ConfigService')
    def test_setup_complete(self, mock_config_service, client, monkeypatch):
        """Test setup complete endpoint."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        mock_config_instance = mock_config_service.return_value
        mock_config_instance.is_configured.return_value = {
            'is_configured': False,
            'app_id': None,
            'installation_id': None,
            'has_private_key': False
        }

        monkeypatch.setenv('GITHUB_APP_ID', '12345')

        response = client.get('/setup/complete?installation_id=67890&setup_action=install', headers=make_basic_auth_headers())

        assert response.status_code == 200
        mock_config_instance.store_github_installation_id.assert_called_once_with('67890')

    @patch('app.routes.setup.ConfigService')
    def test_setup_complete_no_installation_id(self, mock_config_service, client, monkeypatch):
        """Test setup complete without installation_id."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        mock_config_instance = mock_config_service.return_value
        mock_config_instance.is_configured.return_value = {
            'is_configured': False,
            'app_id': None,
            'installation_id': None,
            'has_private_key': False
        }

        response = client.get('/setup/complete', headers=make_basic_auth_headers())

        assert response.status_code == 412
        mock_config_instance.store_github_installation_id.assert_not_called()

    @patch('app.routes.setup.ConfigService')
    def test_setup_page_already_configured(self, mock_config_service, client, monkeypatch):
        """Test that setup page redirects when already configured."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        mock_config_instance = mock_config_service.return_value
        mock_config_instance.is_configured.return_value = {
            'is_configured': True,
            'app_id': '12345',
            'installation_id': '67890',
            'has_private_key': True
        }

        response = client.get('/setup/', headers=make_basic_auth_headers())

        assert response.status_code == 200
        assert b'Already Configured' in response.data

    @patch('app.routes.setup.GitHubService.exchange_code')
    @patch('app.routes.setup.ConfigService')
    def test_setup_callback_already_configured(self, mock_config_service, mock_exchange, client, monkeypatch):
        """Test that setup callback blocks when already configured."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        mock_config_instance = mock_config_service.return_value
        mock_config_instance.is_configured.return_value = {
            'is_configured': True,
            'app_id': '12345',
            'installation_id': '67890',
            'has_private_key': True
        }

        response = client.get('/setup/callback?code=test-code-123', headers=make_basic_auth_headers())

        assert response.status_code == 200
        assert b'Already Configured' in response.data
        mock_exchange.assert_not_called()

    @patch('app.routes.setup.GitHubService.exchange_code')
    @patch('app.routes.setup.ConfigService')
    def test_setup_callback_store_config_error(self, mock_config_service, mock_exchange, client, monkeypatch):
        """Test setup callback when storing config fails."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        mock_exchange.return_value = {
            'id': 12345,
            'pem': 'FAKE_PEM',
            'slug': 'test-app',
            'webhook_secret': 'FAKE_WEBHOOK_SECRET',
            'html_url': 'https://github.com/apps/test-app'
        }

        mock_config_instance = mock_config_service.return_value
        mock_config_instance.is_configured.return_value = {
            'is_configured': False,
            'app_id': None,
            'installation_id': None,
            'has_private_key': False
        }
        mock_config_instance.store_github_app_id.side_effect = Exception("Storage error")

        response = client.get('/setup/callback?code=test-code-123', headers=make_basic_auth_headers())

        assert response.status_code == 507

    @patch('app.routes.setup.GitHubService.get_installation_url')
    @patch('app.routes.setup.GitHubService.exchange_code')
    @patch('app.routes.setup.ConfigService')
    def test_setup_callback_no_app_slug(self, mock_config_service, mock_exchange, mock_get_url, client, monkeypatch):
        """Test setup callback when app slug is missing."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        mock_exchange.return_value = {
            'id': 12345,
            'pem': 'FAKE_PEM',
            'slug': None,
            'webhook_secret': 'FAKE_WEBHOOK_SECRET',
            'html_url': 'https://github.com/apps/test-app'
        }

        mock_config_instance = mock_config_service.return_value
        mock_config_instance.is_configured.return_value = {
            'is_configured': False,
            'app_id': None,
            'installation_id': None,
            'has_private_key': False
        }

        response = client.get('/setup/callback?code=test-code-123', headers=make_basic_auth_headers())

        assert response.status_code == 412

    @patch('app.routes.setup.GitHubService.exchange_code')
    @patch('app.routes.setup.ConfigService')
    def test_setup_callback_exchange_error(self, mock_config_service, mock_exchange, client, monkeypatch):
        """Test setup callback when code exchange fails."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        mock_exchange.side_effect = Exception("Exchange failed")

        mock_config_instance = mock_config_service.return_value
        mock_config_instance.is_configured.return_value = {
            'is_configured': False,
            'app_id': None,
            'installation_id': None,
            'has_private_key': False
        }

        response = client.get('/setup/callback?code=test-code-123', headers=make_basic_auth_headers())

        assert response.status_code == 500

    @patch('app.routes.setup.ConfigService')
    def test_setup_complete_store_error(self, mock_config_service, client, monkeypatch):
        """Test setup complete when storing installation_id fails."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        mock_config_instance = mock_config_service.return_value
        mock_config_instance.is_configured.return_value = {
            'is_configured': False,
            'app_id': None,
            'installation_id': None,
            'has_private_key': False
        }
        mock_config_instance.store_github_installation_id.side_effect = Exception("Storage error")

        response = client.get('/setup/complete?installation_id=67890', headers=make_basic_auth_headers())

        assert response.status_code == 500

    @patch('app.routes.setup.os._exit')
    @patch('app.routes.setup.ConfigService')
    def test_trigger_restart(self, mock_config_service, mock_exit, client, monkeypatch):
        """Test trigger_restart endpoint."""
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        mock_config_instance = mock_config_service.return_value
        # Set to False so before_request doesn't block
        mock_config_instance.is_configured.return_value = {
            'is_configured': False,
            'app_id': None,
            'installation_id': None,
            'has_private_key': False
        }

        # os._exit terminates immediately, so we catch the error from Flask
        # about the view function not returning a response
        try:
            client.post('/setup/trigger-restart', headers=make_basic_auth_headers())
        except TypeError:
            # Expected - os._exit is mocked so it returns None, causing Flask to error
            pass

        mock_exit.assert_called_once_with(1)
