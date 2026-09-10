"""
Tests for POST /runner/preempted and the metadata the manager stamps for the VM notifier.
"""
from unittest.mock import MagicMock, patch

import pytest
from google.api_core import exceptions as gapi_exceptions

from app.clients import gcloud_client
from app.clients.gcloud_client import GCloudClient
from app.routes.runner import classify_preemption_report

MANAGER_URL = 'https://github-runners-manager-uc1-123.us-central1.run.app'
VM_SA = 'github-runners@proj.iam.gserviceaccount.com'


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('MANAGER_URL', MANAGER_URL)
    monkeypatch.setenv('RUNNER_SERVICE_ACCOUNT_EMAIL', VM_SA)
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'proj')


def _claims(instance='gcp-runner-42', zone='us-central1-c', project='proj', full=True):
    claims = {'aud': MANAGER_URL, 'email': VM_SA, 'email_verified': True}
    if full:
        claims['google'] = {'compute_engine': {'instance_name': instance, 'zone': zone, 'project_id': project,
                                               'instance_id': '123'}}
    return claims


class TestClassifyPreemptionReport:
    @pytest.mark.parametrize('body,expected', [
        ({'reason': 'preempted', 'preempted': 'TRUE', 'runner_active': True}, (True, 'preempted')),
        ({'reason': 'shutdown', 'preempted': 'TRUE', 'runner_active': False}, (True, 'preempted')),
        ({'reason': 'shutdown', 'preempted': 'FALSE', 'runner_active': True}, (True, 'shutdown-while-running')),
        ({'reason': 'shutdown', 'preempted': 'FALSE', 'runner_active': 'true'}, (True, 'shutdown-while-running')),
        ({'reason': 'shutdown', 'preempted': 'FALSE', 'runner_active': False}, (False, 'shutdown')),
        ({}, (False, 'unknown')),
    ])
    def test_table(self, body, expected):
        assert classify_preemption_report(body) == expected


class TestPreemptedRoute:
    def test_unconfigured_returns_503(self, client, monkeypatch):
        monkeypatch.delenv('MANAGER_URL', raising=False)
        monkeypatch.delenv('RUNNER_SERVICE_ACCOUNT_EMAIL', raising=False)
        assert client.post('/runner/preempted', headers={'Authorization': 'Bearer t'}).status_code == 503

    def test_missing_token_returns_403(self, client, configured):
        assert client.post('/runner/preempted', json={'reason': 'preempted'}).status_code == 403

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_wrong_caller_returns_403(self, verify, client, configured):
        verify.return_value = {**_claims(), 'email': 'someone@example.com'}
        assert client.post('/runner/preempted', headers={'Authorization': 'Bearer t'},
                           json={'reason': 'preempted'}).status_code == 403

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_token_without_compute_claims_returns_403(self, verify, client, configured):
        verify.return_value = _claims(full=False)
        response = client.post('/runner/preempted', headers={'Authorization': 'Bearer t'}, json={'reason': 'preempted'})
        assert response.status_code == 403
        assert 'compute_engine' in response.get_json()['message']

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_other_project_returns_403(self, verify, client, configured):
        verify.return_value = _claims(project='evil')
        assert client.post('/runner/preempted', headers={'Authorization': 'Bearer t'},
                           json={'reason': 'preempted'}).status_code == 403

    @patch('app.routes.runner.GCloudClient')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_preemption_is_logged_and_labelled_using_token_identity(self, verify, gcloud, client, configured, caplog):
        verify.return_value = _claims(instance='gcp-runner-42', zone='us-central1-c')
        gcloud.return_value.mark_instance_preempted.return_value = True
        body = {'reason': 'preempted', 'instance_name': 'spoofed', 'zone': 'us-east1-b', 'runner_name': 'gcp-runner-42',
                'job_id': '42', 'preempted': 'TRUE', 'preemptible': 'TRUE', 'runner_active': True}
        import logging
        with caplog.at_level(logging.WARNING, logger='app.routes.runner'):
            response = client.post('/runner/preempted', headers={'Authorization': 'Bearer t'}, json=body)
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'recorded'
        assert data['instance'] == 'gcp-runner-42' and data['zone'] == 'us-central1-c'
        gcloud.return_value.mark_instance_preempted.assert_called_once_with(
            'gcp-runner-42', 'us-central1-c', 'preempted', delivery_id='preempt-gcp-runner-42')
        assert any(r.levelno == logging.WARNING and 'PREEMPTED' in r.message and 'job 42' in r.message
                   and 'us-central1-c' in r.message and 'gcp-runner-42' in r.message for r in caplog.records)
        assert not any('spoofed' in r.message or 'us-east1-b' in r.message for r in caplog.records)

    @patch('app.routes.runner.GCloudClient')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_expected_shutdown_is_ignored(self, verify, gcloud, client, configured):
        verify.return_value = _claims()
        body = {'reason': 'shutdown', 'preempted': 'FALSE', 'preemptible': 'TRUE', 'runner_active': False}
        response = client.post('/runner/preempted', headers={'Authorization': 'Bearer t'}, json=body)
        assert response.status_code == 200
        assert response.get_json()['status'] == 'ignored'
        gcloud.return_value.mark_instance_preempted.assert_not_called()

    @patch('app.routes.runner.GCloudClient')
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_label_failure_still_returns_200(self, verify, gcloud, client, configured):
        verify.return_value = _claims()
        gcloud.return_value.mark_instance_preempted.side_effect = RuntimeError('compute down')
        response = client.post('/runner/preempted', headers={'Authorization': 'Bearer t'},
                               json={'reason': 'preempted', 'preempted': 'TRUE'})
        assert response.status_code == 200
        assert response.get_json()['labelled'] is False


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
    monkeypatch.setenv('GOOGLE_CLOUD_ZONE', 'us-central1-b')


@pytest.fixture
def compute(env):
    with patch.object(gcloud_client.compute_v1, 'InstancesClient') as instances, \
            patch.object(gcloud_client.compute_v1, 'RegionInstanceTemplatesClient') as templates, \
            patch.object(gcloud_client.compute_v1, 'ZonesClient') as zones:
        template = MagicMock()
        template.name = 'gcp-ubuntu-24-04-12345678901234'
        template.self_link = 'https://www.googleapis.com/compute/v1/projects/p/regions/us-central1/instanceTemplates/x'
        templates.return_value.list.return_value = [template]
        zones.return_value.list.return_value = []
        yield instances.return_value


class TestMarkInstancePreempted:
    def test_merges_labels_with_fingerprint(self, compute):
        instance = MagicMock()
        instance.labels = {'gha-job-id': '42', 'gha-zone': 'us-central1-c'}
        instance.label_fingerprint = 'fp=='
        compute.get.return_value = instance
        assert GCloudClient().mark_instance_preempted('gcp-runner-42', 'us-central1-c', 'Shutdown While Running') is True
        request = compute.set_labels.call_args.kwargs['request']
        assert request.zone == 'us-central1-c' and request.instance == 'gcp-runner-42'
        labels = dict(request.instances_set_labels_request_resource.labels)
        assert labels['gha-job-id'] == '42'
        assert labels['gha-preempted'] == 'true'
        assert labels['gha-preempt-reason'] == 'shutdown-while-running'
        assert request.instances_set_labels_request_resource.label_fingerprint == 'fp=='

    def test_missing_instance_returns_false(self, compute):
        compute.get.side_effect = gapi_exceptions.NotFound('gone')
        assert GCloudClient().mark_instance_preempted('gcp-runner-42', 'us-central1-c', 'preempted') is False
        compute.set_labels.assert_not_called()


class TestCreationMetadataForNotifier:
    def _metadata(self, compute):
        request = compute.insert.call_args.kwargs['request']
        return {item.key: item.value for item in request.instance_resource.metadata.items}

    def test_manager_url_job_id_and_runner_name_are_stamped(self, compute, monkeypatch):
        monkeypatch.setenv('MANAGER_URL', MANAGER_URL + '/')
        operation = MagicMock()
        operation.result.return_value = None
        operation.error.errors = []
        compute.insert.return_value = operation
        name = GCloudClient().create_runner_instance('tok', 'https://github.com/o/r', 'gcp-ubuntu-24.04', 'o/r', job_id=42)
        metadata = self._metadata(compute)
        assert name == 'gcp-runner-42'
        assert metadata['gha-manager-url'] == MANAGER_URL
        assert metadata['gha-job-id'] == '42'
        assert metadata['gha-runner-name'] == 'gcp-runner-42'
        assert metadata['startup-script'].startswith('cd /actions-runner && ')

    def test_without_manager_url_the_vm_stays_silent(self, compute, monkeypatch):
        monkeypatch.delenv('MANAGER_URL', raising=False)
        operation = MagicMock()
        operation.result.return_value = None
        operation.error.errors = []
        compute.insert.return_value = operation
        GCloudClient().create_runner_instance('tok', 'https://github.com/o/r', 'gcp-ubuntu-24.04')
        metadata = self._metadata(compute)
        assert 'gha-manager-url' not in metadata
        assert 'gha-job-id' not in metadata
        assert metadata['gha-runner-name'].startswith('gcp-runner-')
