"""
GitHub Client for authenticating and interacting with the GitHub API.
"""
import datetime
import os
import time
import jwt
import requests
import logging

REQUEST_TIMEOUT = 30  # seconds
MAX_PAGES = 20  # safety cap for paginated GitHub list endpoints (100 items per page)
MAX_REPOSITORY_PAGES = 100  # installation repositories: the reconciler must see every one (10,000 repos)
READ_RETRIES = 3  # attempts for read-only GitHub calls that answer 5xx (GitHub returns sporadic 502s)
READ_RETRY_BACKOFF = 1.0  # seconds, doubled per attempt
RUN_LOOKBACK_HOURS = 25  # only runs created within this window can still hold queued jobs
RATE_LIMIT_WARN_BELOW = 500  # warn when the installation's remaining GitHub API budget drops under this

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

    def get_registration_token(self, org_name=None, repo_name=None, delivery_id=None):
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
            url = f"https://api.github.com/orgs/{org_name}/actions/runners/registration-token"
            logger.info(
                "Create registration token for organization: %s, delivery_id: %s",
                org_name,
                delivery_id,
            )
        elif repo_name:
            # GitHub Docs: https://t.ly/n0w2a
            url = f"https://api.github.com/repos/{repo_name}/actions/runners/registration-token"
            logger.info(
                "Create registration token for repository: %s, delivery_id: %s",
                repo_name,
                delivery_id,
            )
        else:
            raise ValueError("Either org_name or repo_name must be provided")

        response = requests.post(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()['token']

    # ------------------------------------------------------------------
    # Read-side helpers used by the reconciler
    # ------------------------------------------------------------------

    @staticmethod
    def _headers(token):
        return {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'
        }

    def _get_with_retry(self, url, token, params=None):
        """GET with retries on 5xx (read-only calls only). Returns the final response, not yet checked."""
        response = None
        for attempt in range(READ_RETRIES):
            response = requests.get(url, headers=self._headers(token), params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code < 500:
                remaining = response.headers.get('X-RateLimit-Remaining') if hasattr(response, 'headers') else None
                if remaining is not None and str(remaining).isdigit() and int(remaining) < RATE_LIMIT_WARN_BELOW:
                    logger.warning("GitHub API rate limit is low: %s requests remaining (resets at %s)",
                                   remaining, response.headers.get('X-RateLimit-Reset'))
                return response
            logger.warning("GitHub %s answered %s (attempt %d/%d)", url, response.status_code, attempt + 1, READ_RETRIES)
            if attempt < READ_RETRIES - 1:
                time.sleep(READ_RETRY_BACKOFF * (2 ** attempt))
        return response

    def _get_paginated(self, url, token, key, params=None, max_pages=MAX_PAGES):
        """GET a paginated list endpoint and return the concatenated ``key`` items."""
        items = []
        params = dict(params or {})
        params.setdefault('per_page', 100)
        page = 0
        while url and page < max_pages:
            page += 1
            response = self._get_with_retry(url, token, params=params)
            response.raise_for_status()
            body = response.json()
            items.extend(body.get(key, []) if isinstance(body, dict) else body)
            next_link = response.links.get('next', {}).get('url')
            url = next_link
            params = None  # the next link already carries the query string
        if url:
            logger.warning("Stopped paginating %s after %d pages; results are incomplete", url, max_pages)
        return items

    def list_installation_repositories(self, token=None):
        """
        Repositories the GitHub App installation can see.

        Returns:
            list[dict]: each with full_name, html_url, owner {login, type, html_url}.
        """
        # https://docs.github.com/en/rest/apps/installations#list-repositories-accessible-to-the-app-installation
        token = token or self.get_installation_access_token()
        repos = self._get_paginated('https://api.github.com/installation/repositories', token, 'repositories',
                                    max_pages=MAX_REPOSITORY_PAGES)
        return [
            {
                'full_name': repo.get('full_name'),
                'html_url': repo.get('html_url'),
                'archived': bool(repo.get('archived')),
                'disabled': bool(repo.get('disabled')),
                'owner': {
                    'login': repo.get('owner', {}).get('login'),
                    'type': repo.get('owner', {}).get('type'),
                    'html_url': repo.get('owner', {}).get('html_url'),
                },
            }
            for repo in repos
        ]

    def list_workflow_jobs(self, repo_name, token=None, run_statuses=('queued', 'in_progress')):
        """
        Jobs of every workflow run of ``repo_name`` whose run status is in ``run_statuses``.

        A run counts as in_progress as soon as one of its jobs runs, so queued jobs of a
        partially running workflow are only found by scanning both statuses.

        Returns:
            list[dict]: raw job objects (id, status, conclusion, labels, runner_name, created_at, run_id, ...).
        """
        # https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-repository
        # https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run
        token = token or self.get_installation_access_token()
        jobs = []
        seen_runs = set()
        # GitHub cancels jobs queued for 24 h, so older runs cannot hold a live queued job.
        since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=RUN_LOOKBACK_HOURS))
        for status in run_statuses:
            runs = self._get_paginated(
                f'https://api.github.com/repos/{repo_name}/actions/runs', token, 'workflow_runs',
                params={'status': status, 'created': f">={since.strftime('%Y-%m-%dT%H:%M:%SZ')}"},
            )
            for run in runs:
                run_id = run.get('id')
                if run_id in seen_runs:
                    continue
                seen_runs.add(run_id)
                jobs.extend(self._get_paginated(
                    f'https://api.github.com/repos/{repo_name}/actions/runs/{run_id}/jobs', token, 'jobs',
                    params={'filter': 'latest'},
                ))
        return jobs

    def get_workflow_job(self, repo_name, job_id, token=None):
        """
        Fetch one workflow job.

        Returns:
            dict or None: the job, or None when GitHub returns 404.
        """
        # https://docs.github.com/en/rest/actions/workflow-jobs#get-a-job-for-a-workflow-run
        token = token or self.get_installation_access_token()
        response = self._get_with_retry(f'https://api.github.com/repos/{repo_name}/actions/jobs/{job_id}', token)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _runners_url(org_name=None, repo_name=None):
        if org_name:
            return f'https://api.github.com/orgs/{org_name}/actions/runners'
        if repo_name:
            return f'https://api.github.com/repos/{repo_name}/actions/runners'
        raise ValueError("Either org_name or repo_name must be provided")

    def list_runners(self, org_name=None, repo_name=None, token=None):
        """
        Self-hosted runners registered at the organization (preferred) or repository level.

        Returns:
            list[dict]: id, name, status ('online'/'offline'), busy.
        """
        # https://docs.github.com/en/rest/actions/self-hosted-runners#list-self-hosted-runners-for-an-organization
        token = token or self.get_installation_access_token()
        runners = self._get_paginated(self._runners_url(org_name, repo_name), token, 'runners')
        return [
            {'id': r.get('id'), 'name': r.get('name'), 'status': r.get('status'), 'busy': bool(r.get('busy'))}
            for r in runners
        ]

    def delete_runner(self, runner_id, org_name=None, repo_name=None, token=None):
        """
        Remove a self-hosted runner from GitHub so it can no longer be assigned a job.

        Returns:
            bool: True when GitHub confirmed the removal (204) or the runner was already gone (404).

        Raises:
            requests.HTTPError: for any other status, including 422 when the runner is busy.
        """
        # https://docs.github.com/en/rest/actions/self-hosted-runners#delete-a-self-hosted-runner-from-an-organization
        token = token or self.get_installation_access_token()
        url = f'{self._runners_url(org_name, repo_name)}/{runner_id}'
        response = requests.delete(url, headers=self._headers(token), timeout=REQUEST_TIMEOUT)
        if response.status_code == 404:
            return True
        response.raise_for_status()
        return response.status_code == 204
