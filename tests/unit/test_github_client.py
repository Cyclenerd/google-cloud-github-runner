import pytest
from unittest.mock import patch, MagicMock
from app.clients.github_client import GitHubClient


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set up mock environment variables for GitHub client."""
    monkeypatch.setenv('GITHUB_APP_ID', '12345')
    monkeypatch.setenv('GITHUB_INSTALLATION_ID', '67890')
    monkeypatch.setenv('GITHUB_PRIVATE_KEY_PATH', 'test-key.pem')
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
    monkeypatch.setenv('GITHUB_WEBHOOK_SECRET', 'test-secret')


@pytest.fixture
def mock_private_key_file(tmp_path):
    """Create a temporary private key file."""
    key_file = tmp_path / "test-key.pem"
    key_content = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF8FqH2XZKbNj8xSNiLnmvlYnxF0s
-----END RSA PRIVATE KEY-----"""
    key_file.write_text(key_content)
    return str(key_file)


class TestGitHubClient:
    def test_init_with_env_vars(self, mock_env_vars):
        """Test GitHubClient initialization with environment variables."""
        client = GitHubClient()

        assert client.app_id == '12345'
        assert client.installation_id == '67890'
        assert client.private_key_path == 'test-key.pem'

    def test_init_missing_config(self):
        """Test GitHubClient initialization with missing configuration."""
        with patch.dict('os.environ', {}, clear=True):
            client = GitHubClient()
            assert client.app_id is None
            assert client.installation_id is None

    @patch('builtins.open', create=True)
    def test_get_private_key_from_file(self, mock_open, mock_env_vars):
        """Test retrieving private key from file."""
        mock_file = MagicMock()
        mock_file.read.return_value = "FAKE_PRIVATE_KEY"
        mock_open.return_value.__enter__.return_value = mock_file

        client = GitHubClient()
        key = client._get_private_key()

        assert key == "FAKE_PRIVATE_KEY"
        mock_open.assert_called_once_with('test-key.pem', 'r')

    def test_get_private_key_from_env_var(self, monkeypatch):
        """Test retrieving private key from environment variable."""
        monkeypatch.setenv('GITHUB_APP_ID', '12345')
        monkeypatch.setenv('GITHUB_INSTALLATION_ID', '67890')
        monkeypatch.setenv('GITHUB_PRIVATE_KEY', 'SECRET_KEY_FROM_ENV')
        monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
        monkeypatch.setenv('GITHUB_WEBHOOK_SECRET', 'test-secret')

        client = GitHubClient()
        key = client._get_private_key()

        assert key == "SECRET_KEY_FROM_ENV"

    @patch('app.clients.github_client.jwt.encode')
    @patch.object(GitHubClient, '_get_private_key')
    def test_generate_jwt(self, mock_get_key, mock_jwt_encode, mock_env_vars):
        """Test JWT generation."""
        mock_get_key.return_value = "FAKE_KEY"
        mock_jwt_encode.return_value = "FAKE_JWT_TOKEN"

        client = GitHubClient()
        token = client._generate_jwt()

        assert token == "FAKE_JWT_TOKEN"
        mock_jwt_encode.assert_called_once()

    @patch('app.clients.github_client.requests.post')
    @patch.object(GitHubClient, '_generate_jwt')
    def test_get_installation_access_token(self, mock_jwt, mock_post, mock_env_vars):
        """Test getting installation access token."""
        mock_jwt.return_value = "JWT_TOKEN"
        mock_response = MagicMock()
        mock_response.json.return_value = {'token': 'INSTALL_TOKEN'}
        mock_post.return_value = mock_response

        client = GitHubClient()
        token = client.get_installation_access_token()

        assert token == 'INSTALL_TOKEN'
        mock_post.assert_called_once()

    @patch('app.clients.github_client.requests.post')
    @patch.object(GitHubClient, 'get_installation_access_token')
    def test_get_registration_token_for_repo(self, mock_install_token, mock_post, mock_env_vars):
        """Test getting registration token for a repository."""
        mock_install_token.return_value = "INSTALL_TOKEN"
        mock_response = MagicMock()
        mock_response.json.return_value = {'token': 'REG_TOKEN'}
        mock_post.return_value = mock_response

        client = GitHubClient()
        token = client.get_registration_token(repo_name='owner/repo')

        assert token == 'REG_TOKEN'
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert 'repos/owner/repo' in args[0]

    @patch('app.clients.github_client.requests.post')
    @patch.object(GitHubClient, 'get_installation_access_token')
    def test_get_registration_token_for_org(self, mock_install_token, mock_post, mock_env_vars):
        """Test getting registration token for an organization."""
        mock_install_token.return_value = "INSTALL_TOKEN"
        mock_response = MagicMock()
        mock_response.json.return_value = {'token': 'ORG_TOKEN'}
        mock_post.return_value = mock_response

        client = GitHubClient()
        token = client.get_registration_token(org_name='my-org')

        assert token == 'ORG_TOKEN'
        args, kwargs = mock_post.call_args
        assert 'orgs/my-org' in args[0]

    @patch.object(GitHubClient, 'get_installation_access_token')
    def test_get_registration_token_no_params(self, mock_install_token, mock_env_vars):
        """Test that ValueError is raised when neither org nor repo is provided."""
        mock_install_token.return_value = "FAKE_TOKEN"
        client = GitHubClient()

        with pytest.raises(ValueError, match="Either org_name or repo_name must be provided"):
            client.get_registration_token()

    def test_get_private_key_no_source(self):
        """Test that ValueError is raised when no private key source is configured."""
        with patch.dict('os.environ', {'GITHUB_APP_ID': '12345', 'GITHUB_INSTALLATION_ID': '67890'}, clear=True):
            client = GitHubClient()
            with pytest.raises(ValueError, match="No private key source configured"):
                client._get_private_key()

    @patch.object(GitHubClient, '_get_private_key')
    @patch('app.clients.github_client.jwt.encode')
    def test_generate_jwt_error(self, mock_jwt, mock_get_key, mock_env_vars):
        """Test JWT generation error handling."""
        mock_get_key.side_effect = Exception("Key error")

        client = GitHubClient()
        with pytest.raises(Exception, match="Key error"):
            client._generate_jwt()
