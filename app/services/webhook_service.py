"""
Service for processing webhook events.
"""
import logging
import re
from app.clients import GitHubClient, GCloudClient

logger = logging.getLogger(__name__)


class WebhookService:
    """Service to process GitHub webhook payloads and trigger runner lifecycle actions."""

    def __init__(self):
        """Initialize WebhookService with API clients."""
        self.github_client = GitHubClient()
        self.gcloud_client = GCloudClient()

    def _validate_payload(self, payload):
        """Validate webhook payload structure and content."""
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a dictionary")

        action = payload.get('action')
        if not action or not isinstance(action, str):
            raise ValueError("Invalid or missing action field")

        workflow_job = payload.get('workflow_job', {})
        if not isinstance(workflow_job, dict):
            raise ValueError("Invalid workflow_job field")

        repository = payload.get('repository', {})
        if not isinstance(repository, dict):
            raise ValueError("Invalid repository field")

        # Validate URL formats
        repo_url = repository.get('html_url', '')
        if repo_url and not re.match(r'^https://github\.com/[\w\-\.]+/[\w\-\.]+$', repo_url):
            raise ValueError("Invalid repository URL format")

        return True

    def handle_workflow_job(self, payload, delivery_id=None):
        """Process the workflow_job webhook payload from GitHub.

        Returns:
            dict: A result dict with 'action' and 'runner_name' keys.
        """
        # Validate payload structure
        self._validate_payload(payload)

        # https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_job
        action = payload.get('action')
        workflow_job = payload.get('workflow_job', {})
        labels = workflow_job.get('labels', [])
        repo_url = payload.get('repository', {}).get('html_url')
        repo_name = payload.get('repository', {}).get('full_name')
        repo_owner_url = payload.get('repository', {}).get('owner', {}).get('html_url')
        org_name = payload.get('organization', {}).get('login')

        # Sanitize log output - don't log full payload
        logger.info(
            "Processing workflow_job action: %s for %s, delivery_id: %s",
            action,
            org_name or repo_name,
            delivery_id,
        )

        # https://docs.github.com/en/webhooks/webhook-events-and-payloads?actionType=queued#workflow_job
        if action == 'queued':
            template_name = None
            if labels:
                for label in labels:
                    if label.startswith('gcp-') or label.lower() == 'dependabot':
                        template_name = label
                        break
            if template_name:
                logger.info(
                    "Found matching label prefix: %s, delivery_id: %s",
                    template_name,
                    delivery_id,
                )
                instance_name = self._handle_queued_job(
                    template_name,
                    repo_url,
                    repo_owner_url,
                    repo_name,
                    org_name,
                    delivery_id=delivery_id,
                )
                return {'action': 'created', 'runner_name': instance_name}
            else:
                logger.warning(
                    "No matching gcp- label prefix found for labels %s. "
                    "Ignoring job. delivery_id: %s",
                    labels,
                    delivery_id,
                )
                return {'action': 'ignored', 'runner_name': None}

        # https://docs.github.com/en/webhooks/webhook-events-and-payloads?actionType=completed#workflow_job
        elif action == 'completed':
            runner_name = self._handle_completed_job(
                workflow_job, delivery_id=delivery_id
            )
            return {'action': 'deleted', 'runner_name': runner_name}

        return {'action': 'ignored', 'runner_name': None}

    def _handle_queued_job(
        self,
        template_name,
        repo_url,
        repo_owner_url,
        repo_name,
        org_name,
        delivery_id=None,
    ):
        """Handle queued workflow job.

        Returns:
            str or None: The name of the created runner instance.
        """
        try:
            # Get registration token
            if org_name:
                # Create GitHub Actions runner instance for organization
                token = self.github_client.get_registration_token(
                    org_name=org_name, delivery_id=delivery_id
                )
                return self.gcloud_client.create_runner_instance(
                    token,
                    repo_owner_url,
                    template_name,
                    repo_name,
                    delivery_id=delivery_id,
                )
            elif repo_name:
                # Create GitHub Actions runner instance for repository
                token = self.github_client.get_registration_token(
                    repo_name=repo_name, delivery_id=delivery_id
                )
                return self.gcloud_client.create_runner_instance(
                    token, repo_url, template_name, repo_name, delivery_id=delivery_id
                )
            else:
                logger.error(
                    "Neither repository nor organization found in payload. "
                    "Ignoring job. delivery_id: %s",
                    delivery_id,
                )
                return None

        except Exception as e:
            logger.error(
                "Failed to spawn runner: %s, delivery_id: %s", str(e), delivery_id
            )
            raise

    def _handle_completed_job(self, workflow_job, delivery_id=None):
        """Handle completed workflow job.

        Returns:
            str or None: The name of the deleted runner instance.
        """
        runner_name = workflow_job.get('runner_name')
        logger.info(
            "Job completed. Cleaning up runner: %s, delivery_id: %s",
            runner_name,
            delivery_id,
        )

        if not runner_name:
            logger.warning(
                "Job completed but no runner_name found in payload. delivery_id: %s",
                delivery_id,
            )
            return None

        try:
            self.gcloud_client.delete_runner_instance(
                runner_name, delivery_id=delivery_id
            )
            return runner_name
        except Exception as e:
            logger.error(
                "Failed to delete runner %s: %s, delivery_id: %s",
                runner_name,
                str(e),
                delivery_id,
            )
            return runner_name
