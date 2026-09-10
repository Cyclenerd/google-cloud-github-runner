"""
Service for processing webhook events.
"""
import logging
import re
from app.clients import GitHubClient, GCloudClient
from app.clients.gcloud_client import JOB_ID_LABEL, LIVE_INSTANCE_STATUSES
from app.clients.tasks_client import TasksClient

logger = logging.getLogger(__name__)


class WebhookService:
    """Service to process GitHub webhook payloads and trigger runner lifecycle actions."""

    def __init__(self, github_client=None, gcloud_client=None, tasks_client=None):
        """Initialize WebhookService with API clients (injectable for the reconciler and tests)."""
        self.github_client = github_client or GitHubClient()
        self.gcloud_client = gcloud_client or GCloudClient()
        self.tasks_client = tasks_client or TasksClient()

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
                job_id = workflow_job.get('id')
                payload = {
                    'template_name': template_name,
                    'repo_url': repo_url,
                    'repo_owner_url': repo_owner_url,
                    'repo_name': repo_name,
                    'org_name': org_name,
                    'job_id': job_id,
                    'delivery_id': delivery_id,
                }
                if self.tasks_client.enabled and job_id is not None:
                    # Hand the creation to Cloud Tasks: answers GitHub at once, dedupes redeliveries
                    # by job id, retries capacity errors with backoff.
                    try:
                        outcome = self.tasks_client.enqueue_provision(payload, job_id, delivery_id=delivery_id)
                        return {'action': outcome, 'runner_name': None, 'job_id': job_id}
                    except Exception as e:
                        logger.warning(
                            "Could not enqueue provisioning task for job %s (%s); creating the VM inline, "
                            "delivery_id: %s",
                            job_id,
                            e,
                            delivery_id,
                        )
                instance_name = self.provision_runner(
                    template_name,
                    repo_url,
                    repo_owner_url,
                    repo_name,
                    org_name,
                    job_id=job_id,
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

    def provision_runner(
        self,
        template_name,
        repo_url,
        repo_owner_url,
        repo_name,
        org_name,
        job_id=None,
        delivery_id=None,
        name_suffix='',
    ):
        """Create a runner VM for a queued workflow job.

        Shared by the webhook (queued event) and the reconciler, so both go through the
        same registration-token, operation-wait and zone-fallback path.

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
                    job_id=job_id,
                    name_suffix=name_suffix,
                )
            elif repo_name:
                # Create GitHub Actions runner instance for repository
                token = self.github_client.get_registration_token(
                    repo_name=repo_name, delivery_id=delivery_id
                )
                return self.gcloud_client.create_runner_instance(
                    token, repo_url, template_name, repo_name, delivery_id=delivery_id,
                    job_id=job_id, name_suffix=name_suffix,
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

    def provision_from_task(self, payload):
        """Handle one Cloud Tasks provisioning task (idempotent).

        Skips when the job is no longer queued on GitHub or a live VM for the job already exists,
        otherwise provisions through the same path as the webhook.

        Returns:
            dict: {'action': 'created'|'skipped', 'runner_name', 'job_id', 'reason'}.
        """
        job_id = payload.get('job_id')
        repo_name = payload.get('repo_name')
        delivery_id = payload.get('delivery_id')
        result = {'action': 'skipped', 'runner_name': None, 'job_id': job_id, 'reason': ''}
        for key in ('repo_url', 'repo_owner_url'):
            url = payload.get(key) or ''
            if url and not re.match(r'^https://github\.com/[\w\-\.]+(/[\w\-\.]+)?$', url):
                raise ValueError(f"Invalid {key} in provisioning task")

        if job_id is not None and repo_name:
            try:
                job = self.github_client.get_workflow_job(repo_name, job_id)
            except Exception as e:
                logger.warning("Could not re-check job %s before provisioning (%s); provisioning anyway", job_id, e)
                job = {'status': 'queued'}
            if job is None:
                # 404 also means the installation lacks actions:read; an unneeded VM is cleaned in
                # ten minutes, a job left without a runner is not. Provision.
                logger.warning("Job %s not found on GitHub when re-checking; provisioning anyway", job_id)
                job = {'status': 'queued'}
            status = job.get('status')
            if status != 'queued':
                result['reason'] = f"job is {status}"
                logger.info("Provisioning task for job %s skipped: %s, delivery_id: %s", job_id, result['reason'],
                            delivery_id)
                return result
            for vm in self.gcloud_client.list_runner_instances():
                if vm.get('status') in LIVE_INSTANCE_STATUSES and (vm.get('labels') or {}).get(JOB_ID_LABEL) == str(job_id):
                    result['reason'] = f"VM {vm['name']} already exists in zone {vm['zone']}"
                    result['runner_name'] = vm['name']
                    logger.info("Provisioning task for job %s skipped: %s, delivery_id: %s", job_id, result['reason'],
                                delivery_id)
                    return result

        instance_name = self.provision_runner(
            payload.get('template_name'),
            payload.get('repo_url'),
            payload.get('repo_owner_url'),
            repo_name,
            payload.get('org_name'),
            job_id=job_id,
            delivery_id=delivery_id,
        )
        if instance_name is None:
            result['reason'] = 'no matching instance template'
            return result
        return {'action': 'created', 'runner_name': instance_name, 'job_id': job_id, 'reason': ''}

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

        if not runner_name.startswith('gcp-runner-'):
            logger.warning("gcp-runner prefix not found in runner name %s. Ignoring job.", runner_name)
            return

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
