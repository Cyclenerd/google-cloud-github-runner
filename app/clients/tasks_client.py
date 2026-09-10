"""
Cloud Tasks client: one provisioning task per workflow job, named by the job id.

The webhook enqueues instead of creating the VM inline, so it answers GitHub well inside the
10 s delivery timeout, a redelivery cannot double-provision (the task name is the job id), and
capacity errors are retried by the queue with backoff instead of failing the delivery.
"""
import json
import logging
import os

from google.api_core import exceptions as gapi_exceptions

logger = logging.getLogger(__name__)

TASK_NAME_PREFIX = 'job-'
PROVISION_PATH = '/tasks/provision'
# Longest a single attempt may run before Cloud Tasks retries it (max 30 min): a provisioning
# attempt can wait on several insert operations across zones and ladder rungs. Keep the Cloud
# Run request timeout at or above this, or a retry can overlap a still-running attempt.
DISPATCH_DEADLINE_SECONDS = 1800

_shared_client = None


class TasksClient:
    """Thin wrapper around google.cloud.tasks_v2 for the provisioning queue."""

    def __init__(self):
        # projects/<project>/locations/<region>/queues/<queue>; unset = enqueueing disabled.
        self.queue = os.environ.get('PROVISION_QUEUE', '').strip()
        self.manager_url = os.environ.get('MANAGER_URL', '').strip().rstrip('/')
        self.invoker_email = os.environ.get('PROVISION_INVOKER_EMAIL', '').strip()
        self._client = None

    @property
    def enabled(self):
        return bool(self.queue and self.manager_url and self.invoker_email)

    def _get_client(self):
        global _shared_client
        if self._client is None:
            if _shared_client is None:
                from google.cloud import tasks_v2  # imported lazily: only needed when a queue is configured
                _shared_client = tasks_v2.CloudTasksClient()  # one gRPC channel per process, not per request
            self._client = _shared_client
        return self._client

    @staticmethod
    def task_id_for(job_id):
        return f"{TASK_NAME_PREFIX}{job_id}"

    def enqueue_provision(self, payload, job_id, delivery_id=None):
        """
        Enqueue one provisioning task for ``job_id`` carrying ``payload`` (JSON-serialisable dict).

        Returns:
            str: 'enqueued' when the task was created, 'duplicate' when a task with this job id
            already exists (a redelivery), never both.

        Raises:
            RuntimeError: when the queue is not configured.
            google.api_core.exceptions.GoogleAPICallError: when Cloud Tasks refuses the task.
        """
        if not self.enabled:
            raise RuntimeError('PROVISION_QUEUE, MANAGER_URL and PROVISION_INVOKER_EMAIL must be set to enqueue')
        from google.cloud import tasks_v2
        from google.protobuf import duration_pb2
        task = tasks_v2.Task(
            name=f"{self.queue}/tasks/{self.task_id_for(job_id)}",
            dispatch_deadline=duration_pb2.Duration(seconds=DISPATCH_DEADLINE_SECONDS),
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=f"{self.manager_url}{PROVISION_PATH}",
                headers={'Content-Type': 'application/json'},
                body=json.dumps(payload).encode('utf-8'),
                oidc_token=tasks_v2.OidcToken(service_account_email=self.invoker_email, audience=self.manager_url),
            ),
        )
        try:
            created = self._get_client().create_task(request=tasks_v2.CreateTaskRequest(parent=self.queue, task=task))
        except gapi_exceptions.AlreadyExists:
            logger.info(
                "Provisioning task for job %s already exists; ignoring redelivery, delivery_id: %s", job_id, delivery_id
            )
            return 'duplicate'
        logger.info("Enqueued provisioning task %s for job %s, delivery_id: %s", created.name, job_id, delivery_id)
        return 'enqueued'
