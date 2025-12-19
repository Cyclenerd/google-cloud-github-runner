"""
Service for GitHub App specific logic.
"""
import json
import os
import requests
import logging

REQUEST_TIMEOUT = 30  # seconds

logger = logging.getLogger(__name__)


class GitHubService:
    """Service to handle GitHub App manifest generation and code exchange."""

    @staticmethod
    def generate_manifest(base_url):
        """Generate the GitHub App Manifest JSON."""

        project_id = os.environ.get('GOOGLE_CLOUD_PROJECT', 'unknown project')

        # Generate name with prefix "GCP " and project_id
        # GitHub App name limit is 34 characters.
        # This leaves 30 chars for project_id, which matches GCP project ID max length.
        app_name = f"GCP {project_id[:30]}"

        # https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest#github-app-manifest-parameters
        description = (f"Self-Hosted GitHub Actions Runners manager for Google Cloud Platform "
                       f"(Project: {project_id}, URL: {base_url})")
        manifest = {
            "name": app_name,
            "description": description,
            "url": base_url,
            "hook_attributes": {
                "url": f"{base_url}/webhook",
                "active": True
            },
            "redirect_url": f"{base_url}/setup/callback",
            "setup_url": f"{base_url}/setup/complete",
            "public": False,
            "default_permissions": {
                "administration": "write",
                "organization_self_hosted_runners": "write",
                "actions": "read"
            },
            "default_events": [
                "workflow_job"
            ]
        }
        return json.dumps(manifest)

    @staticmethod
    def exchange_code(code):
        """Exchange the temporary code for the app configuration."""
        url = f"https://api.github.com/app-manifests/{code}/conversions"
        response = requests.post(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def get_installation_url(app_slug):
        """Return the URL to install the GitHub App."""
        return f"https://github.com/apps/{app_slug}/installations/new"
