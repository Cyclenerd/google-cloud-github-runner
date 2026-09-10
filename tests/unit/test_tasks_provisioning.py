"""
Tests for the Cloud Tasks hand-off: enqueue with per-job dedup, webhook behaviour, task handler.
"""
import json
from unittest.mock import MagicMock, Mock, patch

import pytest
from google.api_core import exceptions as gapi_exceptions

from app.clients.gcloud_client import InstanceCreationError, ZoneCapacityError
from app.clients.tasks_client import TasksClient
from app.services.webhook_service import WebhookService

QUEUE = 'projects/proj/locations/us-central1/queues/github-runners-provision-uc1'
MANAGER_URL = 'https://github-runners-manager-uc1-123.us-central1.run.app'
INVOKER = 'github-runners-provisioner@proj.iam.gserviceaccount.com'

PAYLOAD = {
    'action': 'queued',
    'workflow_job': {'id': 4242, 'labels': ['gcp-ubuntu-24-04-std16']},
    'repository': {'html_url': 'https://github.com/example-org/example-repo', 'full_name': 'example-org/example-repo',
                   'owner': {'html_url': 'https://github.com/example-org'}},
    'organization': {'login': 'example-org'},
}


@pytest.fixture
def tasks_env(monkeypatch):
    monkeypatch.setenv('PROVISION_QUEUE', QUEUE)
    monkeypatch.setenv('MANAGER_URL', MANAGER_URL + '/')
    monkeypatch.setenv('PROVISION_INVOKER_EMAIL', INVOKER)
    # the client is shared per process; start each test without one
    monkeypatch.setattr('app.clients.tasks_client._shared_client', None)


class TestTasksClient:
    def test_disabled_without_configuration(self, monkeypatch):
        for name in ('PROVISION_QUEUE', 'MANAGER_URL', 'PROVISION_INVOKER_EMAIL'):
            monkeypatch.delenv(name, raising=False)
        client = TasksClient()
        assert client.enabled is False
        with pytest.raises(RuntimeError):
            client.enqueue_provision({}, 1)

    @patch('google.cloud.tasks_v2.CloudTasksClient')
    def test_enqueue_builds_a_named_oidc_task(self, client_class, tasks_env):
        created = MagicMock()
        created.name = f'{QUEUE}/tasks/job-4242'
        client_class.return_value.create_task.return_value = created
        client = TasksClient()
        assert client.enabled is True

        outcome = client.enqueue_provision({'job_id': 4242, 'template_name': 'x'}, 4242, delivery_id='d-1')

        assert outcome == 'enqueued'
        request = client_class.return_value.create_task.call_args.kwargs['request']
        assert request.parent == QUEUE
        task = request.task
        assert task.name == f'{QUEUE}/tasks/job-4242', 'task name is the job id: redeliveries collide'
        assert task.dispatch_deadline.seconds == 1800, 'one attempt may run as long as the longest provisioning'
        assert task.http_request.url == MANAGER_URL + '/tasks/provision'
        assert task.http_request.oidc_token.service_account_email == INVOKER
        assert task.http_request.oidc_token.audience == MANAGER_URL
        assert json.loads(task.http_request.body) == {'job_id': 4242, 'template_name': 'x'}

    @patch('google.cloud.tasks_v2.CloudTasksClient')
    def test_redelivery_is_a_duplicate_not_an_error(self, client_class, tasks_env, caplog):
        client_class.return_value.create_task.side_effect = gapi_exceptions.AlreadyExists('exists')
        with caplog.at_level('INFO', logger='app.clients.tasks_client'):
            assert TasksClient().enqueue_provision({}, 4242, delivery_id='d-2') == 'duplicate'
        assert any('already exists' in r.message and 'd-2' in r.message for r in caplog.records)

    @patch('google.cloud.tasks_v2.CloudTasksClient')
    def test_other_api_errors_propagate(self, client_class, tasks_env):
        client_class.return_value.create_task.side_effect = gapi_exceptions.ServiceUnavailable('down')
        with pytest.raises(gapi_exceptions.ServiceUnavailable):
            TasksClient().enqueue_provision({}, 4242)


def _service(tasks_enabled=True, enqueue=None):
    github = Mock()
    github.get_registration_token.return_value = 'tok'
    gcloud = Mock()
    gcloud.create_runner_instance.return_value = 'gcp-runner-4242'
    gcloud.list_runner_instances.return_value = []
    tasks = Mock()
    tasks.enabled = tasks_enabled
    if enqueue is not None:
        tasks.enqueue_provision.side_effect = enqueue
    else:
        tasks.enqueue_provision.return_value = 'enqueued'
    return WebhookService(github_client=github, gcloud_client=gcloud, tasks_client=tasks), github, gcloud, tasks


class TestWebhookEnqueues:
    def test_queued_job_is_enqueued_and_no_vm_is_created_inline(self):
        service, github, gcloud, tasks = _service()
        result = service.handle_workflow_job(PAYLOAD, delivery_id='d-3')
        assert result == {'action': 'enqueued', 'runner_name': None, 'job_id': 4242}
        payload, job_id = tasks.enqueue_provision.call_args.args
        assert job_id == 4242
        assert payload == {
            'template_name': 'gcp-ubuntu-24-04-std16', 'repo_url': 'https://github.com/example-org/example-repo',
            'repo_owner_url': 'https://github.com/example-org', 'repo_name': 'example-org/example-repo',
            'org_name': 'example-org', 'job_id': 4242, 'delivery_id': 'd-3',
        }
        gcloud.create_runner_instance.assert_not_called()
        github.get_registration_token.assert_not_called()

    def test_redelivery_reports_duplicate(self):
        service, _, gcloud, _ = _service(enqueue=lambda *a, **k: 'duplicate')
        assert service.handle_workflow_job(PAYLOAD)['action'] == 'duplicate'
        gcloud.create_runner_instance.assert_not_called()

    def test_enqueue_failure_falls_back_to_inline_creation(self, caplog):
        service, _, gcloud, _ = _service(enqueue=RuntimeError('tasks down'))
        with caplog.at_level('WARNING', logger='app.services.webhook_service'):
            result = service.handle_workflow_job(PAYLOAD, delivery_id='d-4')
        assert result == {'action': 'created', 'runner_name': 'gcp-runner-4242'}
        gcloud.create_runner_instance.assert_called_once()
        assert any('creating the VM inline' in r.message and 'd-4' in r.message for r in caplog.records)

    def test_without_a_queue_the_webhook_creates_inline(self):
        service, _, gcloud, tasks = _service(tasks_enabled=False)
        assert service.handle_workflow_job(PAYLOAD)['action'] == 'created'
        tasks.enqueue_provision.assert_not_called()
        gcloud.create_runner_instance.assert_called_once()

    def test_job_without_id_is_created_inline(self):
        service, _, gcloud, tasks = _service()
        payload = {**PAYLOAD, 'workflow_job': {'labels': ['gcp-ubuntu-24-04-std16']}}
        assert service.handle_workflow_job(payload)['action'] == 'created'
        tasks.enqueue_provision.assert_not_called()


TASK = {'template_name': 'gcp-ubuntu-24-04-std16', 'repo_url': 'https://github.com/example-org/example-repo',
        'repo_owner_url': 'https://github.com/example-org', 'repo_name': 'example-org/example-repo',
        'org_name': 'example-org', 'job_id': 4242, 'delivery_id': 'd-5'}


class TestProvisionFromTask:
    def test_creates_when_job_still_queued_and_no_vm(self):
        service, github, gcloud, _ = _service()
        github.get_workflow_job.return_value = {'id': 4242, 'status': 'queued'}
        result = service.provision_from_task(TASK)
        assert result['action'] == 'created' and result['runner_name'] == 'gcp-runner-4242'
        kwargs = gcloud.create_runner_instance.call_args.kwargs
        assert kwargs['job_id'] == 4242 and kwargs['name_suffix'] == ''
        github.get_registration_token.assert_called_once_with(org_name='example-org', delivery_id='d-5')

    @pytest.mark.parametrize('job,reason', [
        ({'status': 'in_progress'}, 'job is in_progress'),
        ({'status': 'completed'}, 'job is completed'),
    ])
    def test_skips_when_job_no_longer_queued(self, job, reason):
        service, github, gcloud, _ = _service()
        github.get_workflow_job.return_value = job
        result = service.provision_from_task(TASK)
        assert result['action'] == 'skipped' and result['reason'] == reason
        gcloud.create_runner_instance.assert_not_called()

    def test_skips_when_a_live_vm_for_the_job_exists(self):
        service, github, gcloud, _ = _service()
        github.get_workflow_job.return_value = {'status': 'queued'}
        gcloud.list_runner_instances.return_value = [
            {'name': 'gcp-runner-4242', 'zone': 'us-central1-c', 'status': 'RUNNING', 'labels': {'gha-job-id': '4242'}},
            {'name': 'gcp-runner-1', 'zone': 'us-central1-b', 'status': 'RUNNING', 'labels': {'gha-job-id': '1'}},
        ]
        result = service.provision_from_task(TASK)
        assert result['action'] == 'skipped' and 'already exists' in result['reason']
        gcloud.create_runner_instance.assert_not_called()

    def test_stopping_vm_does_not_count(self):
        service, github, gcloud, _ = _service()
        github.get_workflow_job.return_value = {'status': 'queued'}
        gcloud.list_runner_instances.return_value = [
            {'name': 'gcp-runner-4242', 'zone': 'us-central1-c', 'status': 'STOPPING', 'labels': {'gha-job-id': '4242'}},
        ]
        assert service.provision_from_task(TASK)['action'] == 'created'

    def test_job_not_found_still_provisions(self, caplog):
        """A 404 can mean the installation lacks actions:read; a spare VM is cheaper than a stuck job."""
        service, github, gcloud, _ = _service()
        github.get_workflow_job.return_value = None
        with caplog.at_level('WARNING', logger='app.services.webhook_service'):
            assert service.provision_from_task(TASK)['action'] == 'created'
        assert any('not found' in r.message for r in caplog.records)

    def test_foreign_urls_are_rejected(self):
        service, github, gcloud, _ = _service()
        github.get_workflow_job.return_value = {'status': 'queued'}
        with pytest.raises(ValueError):
            service.provision_from_task({**TASK, 'repo_url': 'https://evil.example.com/x/y'})
        gcloud.create_runner_instance.assert_not_called()

    def test_recheck_failure_still_provisions(self):
        service, github, gcloud, _ = _service()
        github.get_workflow_job.side_effect = RuntimeError('502')
        assert service.provision_from_task(TASK)['action'] == 'created'

    def test_no_template_is_skipped(self):
        service, github, gcloud, _ = _service()
        github.get_workflow_job.return_value = {'status': 'queued'}
        gcloud.create_runner_instance.return_value = None
        result = service.provision_from_task(TASK)
        assert result['action'] == 'skipped' and 'no matching instance template' in result['reason']


@pytest.fixture
def route_env(monkeypatch):
    monkeypatch.setenv('MANAGER_URL', MANAGER_URL)
    monkeypatch.setenv('PROVISION_INVOKER_EMAIL', INVOKER)


def _claims():
    return {'aud': MANAGER_URL, 'email': INVOKER, 'email_verified': True}


class TestProvisionRoute:
    def test_unconfigured_returns_503(self, client, monkeypatch):
        monkeypatch.delenv('PROVISION_INVOKER_EMAIL', raising=False)
        assert client.post('/tasks/provision', json=TASK, headers={'Authorization': 'Bearer t'}).status_code == 503

    def test_missing_token_returns_403(self, client, route_env):
        assert client.post('/tasks/provision', json=TASK).status_code == 403

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_wrong_caller_returns_403(self, verify, client, route_env):
        verify.return_value = {**_claims(), 'email': 'reconciler@proj.iam.gserviceaccount.com'}
        assert client.post('/tasks/provision', json=TASK, headers={'Authorization': 'Bearer t'}).status_code == 403

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_invalid_payload_is_not_retried(self, verify, client, route_env):
        verify.return_value = _claims()
        response = client.post('/tasks/provision', json={'job_id': None}, headers={'Authorization': 'Bearer t'})
        assert response.status_code == 400

    @patch('app.routes.tasks.WebhookService')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_success_returns_200(self, verify, service_class, client, route_env):
        verify.return_value = _claims()
        service_class.return_value.provision_from_task.return_value = {
            'action': 'created', 'runner_name': 'gcp-runner-4242', 'job_id': 4242, 'reason': ''}
        response = client.post('/tasks/provision', json=TASK,
                               headers={'Authorization': 'Bearer t', 'X-CloudTasks-TaskRetryCount': '2'})
        assert response.status_code == 200
        assert response.get_json()['runner_name'] == 'gcp-runner-4242'

    @patch('app.routes.tasks.WebhookService')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_invalid_task_body_is_not_retried(self, verify, service_class, client, route_env):
        verify.return_value = _claims()
        service_class.return_value.provision_from_task.side_effect = ValueError('Invalid repo_url in provisioning task')
        response = client.post('/tasks/provision', json=TASK, headers={'Authorization': 'Bearer t'})
        assert response.status_code == 200
        assert response.get_json()['status'] == 'skipped'

    @pytest.mark.parametrize('error,status', [
        (ZoneCapacityError('no capacity', code='ZONE_RESOURCE_POOL_EXHAUSTED', zone='us-central1-b'), 503),
        (InstanceCreationError('bad'), 500),
        (RuntimeError('boom'), 500),
    ])
    @patch('app.routes.tasks.WebhookService')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_failures_ask_cloud_tasks_to_retry(self, verify, service_class, error, status, client, route_env):
        verify.return_value = _claims()
        service_class.return_value.provision_from_task.side_effect = error
        response = client.post('/tasks/provision', json=TASK, headers={'Authorization': 'Bearer t'})
        assert response.status_code == status
        assert response.get_json()['status'] == 'retry'
