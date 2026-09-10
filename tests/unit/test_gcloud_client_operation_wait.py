"""
Tests that create_runner_instance waits for the insert operation and surfaces its error.

The fixture ``operation_zone_resource_pool_exhausted.json`` is a real operation recorded
from a real project on 2026-09-09 (n4-standard-16 stockout in us-central1-b).
"""
import concurrent.futures
import json
import logging
import os
from unittest.mock import MagicMock, patch

import pytest
from google.api_core import exceptions as gapi_exceptions
from google.api_core.extended_operation import ExtendedOperation
from google.cloud import compute_v1

from app.clients import gcloud_client
from app.clients.gcloud_client import (
    GCloudClient,
    InstanceCreationError,
    ZoneCapacityError,
    classify_operation_errors,
)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')

TEMPLATE_SELF_LINK = (
    'https://www.googleapis.com/compute/v1/projects/test-project/regions/us-central1/'
    'instanceTemplates/gcp-ubuntu-24-04-12345678901234'
)


class _ComputeCompatOperation(ExtendedOperation):
    """Mirror of the wrapper google-cloud-compute's InstancesClient.insert returns.

    The generated client maps ``error_code``/``error_message`` to the HTTP status of the
    operation, exactly like this. Using it here proves that a real DONE operation carrying
    an ``error`` block makes ``result()`` raise.
    """

    @property
    def error_message(self):
        return self._extended_operation.http_error_message

    @property
    def error_code(self):
        return self._extended_operation.http_error_status_code


def _wrap(operation):
    return _ComputeCompatOperation.make(
        refresh=lambda **kwargs: operation,
        cancel=lambda **kwargs: None,
        extended_operation=operation,
    )


def _recorded_exhausted_operation():
    with open(os.path.join(FIXTURE_DIR, 'operation_zone_resource_pool_exhausted.json')) as fh:
        return compute_v1.Operation.from_json(fh.read(), ignore_unknown_fields=True)


def _operation_with_error(code, message, http_status=400, http_message='BAD REQUEST'):
    payload = {
        'name': 'operation-test',
        'status': 'DONE',
        'progress': 100,
        'httpErrorStatusCode': http_status,
        'httpErrorMessage': http_message,
        'error': {'errors': [{'code': code, 'message': message}]},
    }
    return compute_v1.Operation.from_json(json.dumps(payload), ignore_unknown_fields=True)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
    monkeypatch.setenv('GOOGLE_CLOUD_ZONE', 'us-central1-b')


@pytest.fixture
def clients(env):
    """Patch the compute clients; the template list yields one matching regional template."""
    with patch.object(gcloud_client.compute_v1, 'InstancesClient') as instances, \
            patch.object(gcloud_client.compute_v1, 'RegionInstanceTemplatesClient') as templates, \
            patch.object(gcloud_client.compute_v1, 'ZonesClient', create=True) as zones:
        template = MagicMock()
        template.name = 'gcp-ubuntu-24-04-12345678901234'
        template.self_link = TEMPLATE_SELF_LINK
        templates.return_value.list.return_value = [template]
        zone_b = MagicMock()
        zone_b.name = 'us-central1-b'
        zone_b.region = 'https://www.googleapis.com/compute/v1/projects/test-project/regions/us-central1'
        zone_b.status = 'UP'
        zones.return_value.list.return_value = [zone_b]
        yield instances.return_value, templates.return_value


class TestOperationWait:
    def test_recorded_zone_exhausted_operation_raises_and_logs_code(self, clients, caplog):
        """A real ZONE_RESOURCE_POOL_EXHAUSTED operation must not be reported as success."""
        instances, _ = clients
        instances.insert.return_value = _wrap(_recorded_exhausted_operation())
        client = GCloudClient()

        with caplog.at_level(logging.INFO, logger='app.clients.gcloud_client'):
            with pytest.raises(ZoneCapacityError) as excinfo:
                client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-ubuntu-24.04',
                                              delivery_id='d-1')

        assert excinfo.value.code == 'ZONE_RESOURCE_POOL_EXHAUSTED_WITH_DETAILS'
        assert excinfo.value.zone == 'us-central1-b'
        assert any('ZONE_RESOURCE_POOL_EXHAUSTED_WITH_DETAILS' in r.message and 'd-1' in r.message
                   for r in caplog.records)

    def test_unknown_operation_error_is_raised_not_swallowed(self, clients, caplog):
        instances, _ = clients
        instances.insert.return_value = _wrap(_operation_with_error('INVALID_FIELD_VALUE', "Invalid value for field 'x'"))
        client = GCloudClient()

        with caplog.at_level(logging.ERROR, logger='app.clients.gcloud_client'):
            with pytest.raises(InstanceCreationError) as excinfo:
                client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-ubuntu-24.04',
                                              delivery_id='d-2')

        assert not isinstance(excinfo.value, ZoneCapacityError)
        assert 'INVALID_FIELD_VALUE' in str(excinfo.value)
        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any('INVALID_FIELD_VALUE' in r.message and "Invalid value for field 'x'" in r.message
                   and 'd-2' in r.message for r in error_logs)
        instances.insert.assert_called_once()

    def test_operation_timeout_raises_and_does_not_retry(self, clients, caplog):
        """A timed-out insert may still create the VM, so it must never be retried elsewhere."""
        instances, _ = clients
        operation = MagicMock()
        operation.name = 'operation-slow'
        operation.result.side_effect = concurrent.futures.TimeoutError()
        instances.insert.return_value = operation
        client = GCloudClient()

        with caplog.at_level(logging.ERROR, logger='app.clients.gcloud_client'):
            with pytest.raises(InstanceCreationError) as excinfo:
                client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-ubuntu-24.04',
                                              delivery_id='d-3')

        assert not isinstance(excinfo.value, ZoneCapacityError)
        assert 'timed out' in str(excinfo.value)
        assert instances.insert.call_count == 1
        assert any('timed out' in r.message and 'd-3' in r.message for r in caplog.records)

    def test_success_waits_with_bounded_timeout(self, clients, monkeypatch):
        monkeypatch.setenv('GCE_INSERT_TIMEOUT_SECONDS', '45')
        instances, _ = clients
        operation = MagicMock()
        operation.name = 'operation-ok'
        operation.result.return_value = None
        operation.error.errors = []
        instances.insert.return_value = operation
        client = GCloudClient()

        name = client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-ubuntu-24.04')

        assert name.startswith('gcp-runner-')
        operation.result.assert_called_once_with(timeout=45)

    def test_generic_api_error_without_operation_errors_is_raised(self, clients):
        instances, _ = clients
        operation = MagicMock()
        operation.name = 'operation-x'
        operation.result.side_effect = gapi_exceptions.InternalServerError('boom')
        operation.error.errors = []
        instances.insert.return_value = operation
        client = GCloudClient()

        with pytest.raises(InstanceCreationError, match='boom'):
            client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-ubuntu-24.04')


class TestClassifyOperationErrors:
    @pytest.mark.parametrize('code,message', [
        ('ZONE_RESOURCE_POOL_EXHAUSTED', 'The zone does not have enough resources'),
        ('ZONE_RESOURCE_POOL_EXHAUSTED_WITH_DETAILS', 'The zone does not have enough resources'),
        ('QUOTA_EXCEEDED', "Quota 'N4_CPUS' exceeded"),
        ('RESOURCE_UNAVAILABLE', 'A n4-standard-16 VM instance is currently unavailable in the us-central1-b zone'),
        ('UNKNOWN', 'reason: stockout'),
    ])
    def test_capacity_errors_are_retry_elsewhere(self, code, message):
        errors = [compute_v1.Errors(code=code, message=message)]
        retry_elsewhere, summary = classify_operation_errors(errors)
        assert retry_elsewhere is True
        assert code in summary

    @pytest.mark.parametrize('code,message', [
        ('INVALID_FIELD_VALUE', "Invalid value for field 'resource.name'"),
        ('RESOURCE_NOT_FOUND', 'The resource was not found'),
        ('CONDITION_NOT_MET', 'Some condition'),
        ('', ''),
    ])
    def test_other_errors_are_fatal(self, code, message):
        errors = [compute_v1.Errors(code=code, message=message)]
        retry_elsewhere, _ = classify_operation_errors(errors)
        assert retry_elsewhere is False

    def test_recorded_operation_classifies_via_error_info_reason(self):
        errors = list(_recorded_exhausted_operation().error.errors)
        retry_elsewhere, summary = classify_operation_errors(errors)
        assert retry_elsewhere is True
        assert 'ZONE_RESOURCE_POOL_EXHAUSTED_WITH_DETAILS' in summary
        assert 'us-central1-b' in summary
