import pytest
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock
from app.services.config_service import ConfigService


@pytest.fixture
def temp_env_file():
    """Create a temporary .env file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
        env_path = f.name
    yield env_path
    if os.path.exists(env_path):
        os.remove(env_path)


class TestConfigServiceInit:
    def test_init_cloud_run_mode(self):
        """Test ConfigService initialization in Cloud Run mode."""
        with patch.dict(os.environ, {
            'GOOGLE_CLOUD_PROJECT': 'test-project',
            'GCP_REGION': 'us-west1',
            'K_SERVICE': 'test-service'
        }):
            with patch('app.services.config_service.secretmanager.SecretManagerServiceClient') as mock_sm:
                config = ConfigService()
                assert config.project_id == 'test-project'
                assert config.region == 'us-west1'
                assert config.service_name == 'test-service'
                assert config.is_cloud_run is True
                mock_sm.assert_called_once()

    def test_init_cloud_run_without_project_id(self):
        """Test ConfigService initialization in Cloud Run without project ID."""
        with patch.dict(os.environ, {'K_SERVICE': 'test-service'}, clear=True):
            with patch('app.services.config_service.secretmanager.SecretManagerServiceClient'):
                config = ConfigService()
                assert config.project_id is None
                assert config.is_cloud_run is True

    def test_init_cloud_run_secret_client_error(self):
        """Test ConfigService initialization when secret client fails."""
        with patch.dict(os.environ, {'K_SERVICE': 'test-service', 'GOOGLE_CLOUD_PROJECT': 'test'}, clear=True):
            with patch('app.services.config_service.secretmanager.SecretManagerServiceClient',
                       side_effect=Exception("Failed")):
                config = ConfigService()
                assert config.is_cloud_run is False

    def test_init_local_mode(self):
        """Test ConfigService initialization in local mode."""
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigService()
            assert config.is_cloud_run is False
            assert config.secret_client is None


class TestStoreGitHubAppId:
    def test_store_app_id_cloud(self):
        """Test storing app ID in cloud mode."""
        with patch.dict(os.environ, {
            'GOOGLE_CLOUD_PROJECT': 'test-project',
            'K_SERVICE': 'test-service'
        }):
            with patch('app.services.config_service.secretmanager.SecretManagerServiceClient') as mock_sm:
                mock_client = Mock()
                mock_sm.return_value = mock_client
                config = ConfigService()

                result = config.store_github_app_id('123456')

                assert result is True
                mock_client.add_secret_version.assert_called_once()
                call_args = mock_client.add_secret_version.call_args[1]['request']
                assert call_args['parent'] == 'projects/test-project/secrets/github-app-id'
                assert call_args['payload']['data'] == b'123456'

    def test_store_app_id_local(self, temp_env_file):
        """Test storing app ID in local mode."""
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigService()
            with patch('app.services.config_service.ConfigService._update_env_file') as mock_update:
                result = config.store_github_app_id('123456')

                assert result is True
                mock_update.assert_called_once_with('GITHUB_APP_ID', '123456')

    def test_store_app_id_cloud_error(self):
        """Test storing app ID in cloud mode with error."""
        with patch.dict(os.environ, {
            'GOOGLE_CLOUD_PROJECT': 'test-project',
            'K_SERVICE': 'test-service'
        }):
            with patch('app.services.config_service.secretmanager.SecretManagerServiceClient') as mock_sm:
                mock_client = Mock()
                mock_client.add_secret_version.side_effect = Exception("Secret error")
                mock_sm.return_value = mock_client
                config = ConfigService()

                with pytest.raises(Exception):
                    config.store_github_app_id('123456')


class TestStoreGitHubInstallationId:
    def test_store_installation_id_cloud(self):
        """Test storing installation ID in cloud mode."""
        with patch.dict(os.environ, {
            'GOOGLE_CLOUD_PROJECT': 'test-project',
            'K_SERVICE': 'test-service'
        }):
            with patch('app.services.config_service.secretmanager.SecretManagerServiceClient') as mock_sm:
                mock_client = Mock()
                mock_sm.return_value = mock_client
                config = ConfigService()

                result = config.store_github_installation_id('987654')

                assert result is True
                mock_client.add_secret_version.assert_called_once()
                call_args = mock_client.add_secret_version.call_args[1]['request']
                assert call_args['parent'] == 'projects/test-project/secrets/github-installation-id'

    def test_store_installation_id_local(self):
        """Test storing installation ID in local mode."""
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigService()
            with patch('app.services.config_service.ConfigService._update_env_file') as mock_update:
                result = config.store_github_installation_id('987654')

                assert result is True
                mock_update.assert_called_once_with('GITHUB_INSTALLATION_ID', '987654')

    def test_store_installation_id_error(self):
        """Test storing installation ID with error."""
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigService()
            with patch('app.services.config_service.ConfigService._update_env_file',
                       side_effect=Exception("Write error")):
                with pytest.raises(Exception):
                    config.store_github_installation_id('987654')

    def test_store_installation_id_cloud_error(self):
        """Test storing installation ID in cloud mode with error."""
        with patch.dict(os.environ, {
            'GOOGLE_CLOUD_PROJECT': 'test-project',
            'K_SERVICE': 'test-service'
        }):
            with patch('app.services.config_service.secretmanager.SecretManagerServiceClient') as mock_sm:
                mock_client = Mock()
                mock_client.add_secret_version.side_effect = Exception("Secret error")
                mock_sm.return_value = mock_client
                config = ConfigService()

                with pytest.raises(Exception):
                    config.store_github_installation_id('987654')


class TestStoreGitHubPrivateKey:
    def test_store_private_key_cloud(self):
        """Test storing private key in cloud mode."""
        with patch.dict(os.environ, {
            'GOOGLE_CLOUD_PROJECT': 'test-project',
            'K_SERVICE': 'test-service'
        }):
            with patch('app.services.config_service.secretmanager.SecretManagerServiceClient') as mock_sm:
                mock_client = Mock()
                mock_sm.return_value = mock_client
                config = ConfigService()

                result = config.store_github_private_key('-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----')

                assert result is True
                mock_client.add_secret_version.assert_called_once()

    def test_store_private_key_local(self):
        """Test storing private key in local mode."""
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigService()
            private_key = '-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----'

            with patch('os.open') as mock_os_open, \
                 patch('os.fdopen') as mock_fdopen, \
                 patch('app.services.config_service.ConfigService._update_env_file') as mock_update:
                mock_file = MagicMock()
                mock_fdopen.return_value.__enter__.return_value = mock_file

                result = config.store_github_private_key(private_key)

                assert result is True
                mock_os_open.assert_called_once_with('github-private-key.pem', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                mock_file.write.assert_called_once_with(private_key)
                mock_update.assert_called_once_with('GITHUB_PRIVATE_KEY_PATH', 'github-private-key.pem')

    def test_store_private_key_error(self):
        """Test storing private key with error."""
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigService()
            with patch('builtins.open', side_effect=Exception("IO error")):
                with pytest.raises(Exception):
                    config.store_github_private_key('test-key')

    def test_store_private_key_cloud_error(self):
        """Test storing private key in cloud mode with error."""
        with patch.dict(os.environ, {
            'GOOGLE_CLOUD_PROJECT': 'test-project',
            'K_SERVICE': 'test-service'
        }):
            with patch('app.services.config_service.secretmanager.SecretManagerServiceClient') as mock_sm:
                mock_client = Mock()
                mock_client.add_secret_version.side_effect = Exception("Secret error")
                mock_sm.return_value = mock_client
                config = ConfigService()

                with pytest.raises(Exception):
                    config.store_github_private_key('test-key')


class TestStoreGitHubWebhookSecret:
    def test_store_webhook_secret_cloud(self):
        """Test storing webhook secret in cloud mode."""
        with patch.dict(os.environ, {
            'GOOGLE_CLOUD_PROJECT': 'test-project',
            'K_SERVICE': 'test-service'
        }):
            with patch('app.services.config_service.secretmanager.SecretManagerServiceClient') as mock_sm:
                mock_client = Mock()
                mock_sm.return_value = mock_client
                config = ConfigService()

                result = config.store_github_webhook_secret('my-secret-123')

                assert result is True
                mock_client.add_secret_version.assert_called_once()
                call_args = mock_client.add_secret_version.call_args[1]['request']
                assert call_args['parent'] == 'projects/test-project/secrets/github-webhook-secret'

    def test_store_webhook_secret_local(self):
        """Test storing webhook secret in local mode."""
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigService()
            with patch('app.services.config_service.ConfigService._update_env_file') as mock_update:
                result = config.store_github_webhook_secret('my-secret-123')

                assert result is True
                mock_update.assert_called_once_with('GITHUB_WEBHOOK_SECRET', 'my-secret-123')

    def test_store_webhook_secret_error(self):
        """Test storing webhook secret with error."""
        with patch.dict(os.environ, {
            'GOOGLE_CLOUD_PROJECT': 'test-project',
            'K_SERVICE': 'test-service'
        }):
            with patch('app.services.config_service.secretmanager.SecretManagerServiceClient') as mock_sm:
                mock_client = Mock()
                mock_client.add_secret_version.side_effect = Exception("Secret error")
                mock_sm.return_value = mock_client
                config = ConfigService()

                with pytest.raises(Exception):
                    config.store_github_webhook_secret('my-secret-123')

    def test_store_webhook_secret_local_error(self):
        """Test storing webhook secret in local mode with error."""
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigService()
            with patch('app.services.config_service.ConfigService._update_env_file',
                       side_effect=Exception("Write error")):
                with pytest.raises(Exception):
                    config.store_github_webhook_secret('my-secret-123')


class TestUpdateEnvFile:
    def test_update_env_file_new_file(self, temp_env_file):
        """Test updating .env file when it doesn't exist."""
        os.remove(temp_env_file)
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigService()
            original_open = open
            original_exists = os.path.exists

            def mock_open_func(path, *args, **kwargs):
                if path == '.env':
                    return original_open(temp_env_file, *args, **kwargs)
                return original_open(path, *args, **kwargs)

            def mock_exists_func(p):
                if p == '.env':
                    return original_exists(temp_env_file)
                return original_exists(p)

            with patch('builtins.open', mock_open_func):
                with patch('os.path.exists', mock_exists_func):
                    config._update_env_file('TEST_KEY', 'test_value')

        with open(temp_env_file, 'r') as f:
            content = f.read()
            assert 'TEST_KEY=test_value' in content

    def test_update_env_file_existing_key(self):
        """Test updating existing key in .env file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write('TEST_KEY=old_value\n')
            f.write('OTHER_KEY=other_value\n')
            env_path = f.name

        try:
            with patch.dict(os.environ, {}, clear=True):
                config = ConfigService()
                with patch('builtins.open', side_effect=[
                    open(env_path, 'r'),
                    open(env_path, 'w')
                ]) as _:
                    with patch('os.path.exists', return_value=True):
                        config._update_env_file('TEST_KEY', 'new_value')
        finally:
            if os.path.exists(env_path):
                os.remove(env_path)

    def test_update_env_file_append_new_key(self):
        """Test appending new key to existing .env file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write('EXISTING_KEY=existing_value\n')
            env_path = f.name

        try:
            with patch.dict(os.environ, {}, clear=True):
                config = ConfigService()
                with patch('builtins.open', side_effect=[
                    open(env_path, 'r'),
                    open(env_path, 'w')
                ]) as _:
                    with patch('os.path.exists', return_value=True):
                        config._update_env_file('NEW_KEY', 'new_value')
        finally:
            if os.path.exists(env_path):
                os.remove(env_path)


class TestIsConfigured:
    def test_is_configured_cloud_run_complete(self):
        """Test is_configured in Cloud Run with all config."""
        with patch.dict(os.environ, {
            'K_SERVICE': 'test-service',
            'GOOGLE_CLOUD_PROJECT': 'test-project',
            'GITHUB_APP_ID': '123456',
            'GITHUB_INSTALLATION_ID': '987654',
            'GITHUB_PRIVATE_KEY': 'actual-key-content'
        }):
            with patch('app.services.config_service.secretmanager.SecretManagerServiceClient'):
                config = ConfigService()
                result = config.is_configured()

                assert result['is_configured'] is True
                assert result['app_id'] == '123456'
                assert result['installation_id'] == '987654'
                assert result['has_private_key'] is True

    def test_is_configured_cloud_run_incomplete(self):
        """Test is_configured in Cloud Run with incomplete config."""
        with patch.dict(os.environ, {
            'K_SERVICE': 'test-service',
            'GOOGLE_CLOUD_PROJECT': 'test-project',
            'GITHUB_APP_ID': '123456',
            'GITHUB_PRIVATE_KEY': 'initial-value'
        }):
            with patch('app.services.config_service.secretmanager.SecretManagerServiceClient'):
                config = ConfigService()
                result = config.is_configured()

                assert result['is_configured'] is False
                assert result['has_private_key'] is False

    def test_is_configured_local_complete(self, temp_env_file):
        """Test is_configured in local mode with all config."""
        with open(temp_env_file, 'w') as f:
            f.write('test')

        with patch.dict(os.environ, {
            'GITHUB_APP_ID': '123456',
            'GITHUB_INSTALLATION_ID': '987654',
            'GITHUB_PRIVATE_KEY_PATH': temp_env_file
        }, clear=True):
            config = ConfigService()
            result = config.is_configured()

            assert result['is_configured'] is True
            assert result['has_private_key'] is True

    def test_is_configured_local_incomplete(self):
        """Test is_configured in local mode with incomplete config."""
        with patch.dict(os.environ, {
            'GITHUB_APP_ID': '123456'
        }, clear=True):
            config = ConfigService()
            result = config.is_configured()

            assert result['is_configured'] is False

    def test_is_configured_error(self):
        """Test is_configured with error."""
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigService()
            with patch('os.environ.get', side_effect=Exception("Error")):
                result = config.is_configured()

                assert result['is_configured'] is False
                assert result['app_id'] is None


class TestConfigServiceUpdateEnvFile:
    def test_update_env_file_append_key(self, temp_env_file):
        """Test _update_env_file appends key when not found."""
        config = ConfigService()
        with open(temp_env_file, 'w') as f:
            f.write("EXISTING_KEY=value\n")

        original_open = open
        original_exists = os.path.exists

        def mock_open_func(path, *args, **kwargs):
            if path == '.env':
                return original_open(temp_env_file, *args, **kwargs)
            return original_open(path, *args, **kwargs)

        def mock_exists_func(p):
            if p == '.env':
                return original_exists(temp_env_file)
            return original_exists(p)

        with patch('builtins.open', mock_open_func):
            with patch('os.path.exists', mock_exists_func):
                config._update_env_file("NEW_KEY", "new_value")

        with open(temp_env_file, 'r') as f:
            content = f.read()
            assert "NEW_KEY=new_value" in content
            assert "EXISTING_KEY=value" in content

    def test_update_env_file_update_existing_key(self, temp_env_file):
        """Test _update_env_file updates existing key."""
        config = ConfigService()
        with open(temp_env_file, 'w') as f:
            f.write("EXISTING_KEY=old_value\nOTHER_KEY=other\n")

        original_open = open
        original_exists = os.path.exists

        def mock_open_func(path, *args, **kwargs):
            if path == '.env':
                return original_open(temp_env_file, *args, **kwargs)
            return original_open(path, *args, **kwargs)

        def mock_exists_func(p):
            if p == '.env':
                return original_exists(temp_env_file)
            return original_exists(p)

        with patch('builtins.open', mock_open_func):
            with patch('os.path.exists', mock_exists_func):
                config._update_env_file("EXISTING_KEY", "new_value")

        with open(temp_env_file, 'r') as f:
            content = f.read()
            assert "EXISTING_KEY=new_value" in content
            assert "EXISTING_KEY=old_value" not in content
            assert "OTHER_KEY=other" in content

    def test_update_env_file_append_newline(self, temp_env_file):
        """Test _update_env_file appends newline when last line doesn't have one."""
        config = ConfigService()
        with open(temp_env_file, 'w') as f:
            f.write("EXISTING_KEY=value")  # No newline at end

        original_open = open
        original_exists = os.path.exists

        def mock_open_func(path, *args, **kwargs):
            if path == '.env':
                return original_open(temp_env_file, *args, **kwargs)
            return original_open(path, *args, **kwargs)

        def mock_exists_func(p):
            if p == '.env':
                return original_exists(temp_env_file)
            return original_exists(p)

        with patch('builtins.open', mock_open_func):
            with patch('os.path.exists', mock_exists_func):
                config._update_env_file("NEW_KEY", "new_value")

        with open(temp_env_file, 'r') as f:
            content = f.read()
            assert "NEW_KEY=new_value" in content

    def test_store_app_id_error_handling(self, temp_env_file):
        """Test store_github_app_id error handling."""
        with patch.dict(os.environ, {'ENV_FILE': temp_env_file}, clear=True):
            config = ConfigService()
            with patch.object(config, '_update_env_file', side_effect=Exception("Write error")):
                with pytest.raises(Exception, match="Write error"):
                    config._store_app_id_local(12345)
