"""
GitHub Client for authenticating and interacting with the GitHub API.
"""
import os
import time
import jwt
import requests
import logging

REQUEST_TIMEOUT = 30  # seconds

logger = logging.getLogger(__name__)


class GitHubClient:
    """Client for authenticated interactions with the GitHub API as a GitHub App."""

    def __init__(self):
        """Initialize GitHubClient with environment configuration."""
        self.app_id = os.environ.get('GITHUB_APP_ID')
        self.installation_id = os.environ.get('GITHUB_INSTALLATION_ID')
        self.private_key = os.environ.get('GITHUB_PRIVATE_KEY')
        self.private_key_path = os.environ.get('GITHUB_PRIVATE_KEY_PATH')
        self.project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')

        if not all([self.app_id, self.installation_id]) or not (self.private_key_path or self.private_key):
            logger.warning("GitHub App configuration missing.")

    def _get_private_key(self):
        """
        Retrieve the GitHub App private key.

        Returns:
            str: The private key content.

        Raises:
            ValueError: If no private key source is configured.
        """
        # Retrun environment variable
        if self.private_key:
            return self.private_key
        # Return file content
        elif self.private_key_path:
            with open(self.private_key_path, 'r') as f:
                return f.read()
        else:
            raise ValueError("No private key source configured.")

    def _generate_jwt(self):
        """Generates a JWT for GitHub App authentication."""
        try:
            private_key = self._get_private_key()

            payload = {
                'iat': int(time.time()),
                'exp': int(time.time()) + (10 * 60),
                'iss': self.app_id
            }

            encoded_jwt = jwt.encode(payload, private_key, algorithm='RS256')
            return encoded_jwt
        except Exception as e:
            logger.error(f"Error generating JWT: {e}")
            raise

    def get_installation_access_token(self):
        """Obtains an installation access token."""
        # https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app
        jwt_token = self._generate_jwt()
        headers = {
            'Authorization': f'Bearer {jwt_token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'
        }
        url = f'https://api.github.com/app/installations/{self.installation_id}/access_tokens'

        response = requests.post(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        # The installation access token will expire after 1 hour.
        return response.json()['token']

    def get_registration_token(self, org_name=None, repo_name=None):
        """Gets a runner registration token."""
        # https://docs.github.com/en/rest/actions/self-hosted-runners
        token = self.get_installation_access_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'
        }
        if org_name:
            # GitHub Docs: https://t.ly/dAyGK
            url = f'https://api.github.com/orgs/{org_name}/actions/runners/registration-token'
            logger.info(f"Create registration token for organization: {org_name}")
        elif repo_name:
            # GitHub Docs: https://t.ly/n0w2a
            url = f'https://api.github.com/repos/{repo_name}/actions/runners/registration-token'
            logger.info(f"Create registration token for repository: {repo_name}")
        else:
            raise ValueError("Either org_name or repo_name must be provided")

        response = requests.post(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()['token']
