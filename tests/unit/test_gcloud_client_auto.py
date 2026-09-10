"""
Fake-operation tests for the gcp-auto ladder: rung -> zones -> next rung, floor stop, loud failure.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest

from app.clients import gcloud_client
from app.clients.gcloud_client import GCloudClient, InstanceCreationError, ZoneCapacityError
from app.utils.auto_label import InvalidAutoLabel
from tests.unit.test_gcloud_client_operation_wait import _operation_with_error, _recorded_exhausted_operation, _wrap
from tests.unit.test_gcloud_client_zone_fallback import _ok_operation, _zone

TEMPLATE_BASE = 'https://www.googleapis.com/compute/v1/projects/test-project/regions/us-central1/instanceTemplates/'


def _template(name):
    template = MagicMock()
    template.name = name
    template.self_link = TEMPLATE_BASE + name
    return template


ALL_RUNG_TEMPLATES = [
    _template(f'gcp-ubuntu-24-04-{rung}-20260909120000')
    for rung in ('compute-16', 'general-16', 'compute-8', 'general-8', 'compute-4', 'general-4', 'compute-2', 'general-2')
] + [_template('gcp-ubuntu-24-04-20260909120000')]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
    monkeypatch.setenv('GOOGLE_CLOUD_ZONE', 'us-central1-b')
    monkeypatch.delenv('AUTO_TEMPLATE_PREFIX', raising=False)


@pytest.fixture
def clients(env):
    with patch.object(gcloud_client.compute_v1, 'InstancesClient') as instances, \
            patch.object(gcloud_client.compute_v1, 'RegionInstanceTemplatesClient') as templates, \
            patch.object(gcloud_client.compute_v1, 'ZonesClient') as zones:
        templates.return_value.list.return_value = list(ALL_RUNG_TEMPLATES)
        zones.return_value.list.return_value = [_zone('us-central1-b'), _zone('us-central1-a')]
        yield instances.return_value, templates.return_value


def _attempts(instances):
    """(template rung, zone) per insert call, in order."""
    result = []
    for call in instances.insert.call_args_list:
        request = call.kwargs['request']
        template = request.source_instance_template.rsplit('/', 1)[1]
        result.append((template.replace('gcp-ubuntu-24-04-', '').rsplit('-', 1)[0], request.zone))
    return result


def _landed(instances):
    request = instances.insert.call_args_list[-1].kwargs['request']
    return request.instance_resource


def _startup_script(resource):
    return next(item.value for item in resource.metadata.items if item.key == 'startup-script')


class TestAutoLadder:
    def test_first_rung_exhausted_in_every_zone_steps_down_to_next_rung(self, clients, caplog):
        instances, _ = clients
        exhausted = _recorded_exhausted_operation()
        instances.insert.side_effect = [_wrap(exhausted), _wrap(exhausted), _ok_operation()]
        client = GCloudClient()

        with caplog.at_level(logging.INFO, logger='app.clients.gcloud_client'):
            name = client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-auto-compute-16', 'o/r',
                                                 delivery_id='d-auto', job_id=7)

        assert name == 'gcp-runner-7'
        assert _attempts(instances) == [('compute-16', 'us-central1-b'), ('compute-16', 'us-central1-a'),
                                        ('general-16', 'us-central1-b')]
        landed = _landed(instances)
        assert landed.labels['gha-rung'] == 'general-16'
        assert landed.labels['gha-zone'] == 'us-central1-b'
        assert landed.labels['gha-runner'] == 'gcp-auto-compute-16'
        assert landed.labels['gha-job-id'] == '7'
        script = _startup_script(landed)
        assert 'gcp-auto: requested compute-16, landed general-16 in us-central1-b' in script
        assert '--labels gcp-auto-compute-16' in script, 'the runner must register with the job label'
        assert 'ACTIONS_RUNNER_HOOK_JOB_STARTED' in script, 'the landing line must reach the job log'
        assert any('landed general-16' in r.message and 'us-central1-b' in r.message and 'd-auto' in r.message
                   for r in caplog.records)

    def test_exhausted_down_to_the_floor_fails_loudly_and_creates_nothing(self, clients, caplog):
        instances, _ = clients
        instances.insert.side_effect = [_wrap(_recorded_exhausted_operation()) for _ in range(4)]
        client = GCloudClient()

        with caplog.at_level(logging.WARNING, logger='app.clients.gcloud_client'):
            with pytest.raises(ZoneCapacityError) as excinfo:
                client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-auto-compute-16-min16', 'o/r',
                                              delivery_id='d-floor')

        assert _attempts(instances) == [('compute-16', 'us-central1-b'), ('compute-16', 'us-central1-a'),
                                        ('general-16', 'us-central1-b'), ('general-16', 'us-central1-a')]
        message = str(excinfo.value)
        assert 'compute-16' in message and 'general-16' in message and 'floor' in message
        loud = [r for r in caplog.records if r.levelno >= logging.WARNING and 'd-floor' in r.message
                and 'floor' in r.message]
        assert loud, 'expected a WARNING/ERROR naming the floor'
        for needle in ('compute-16', 'general-16', 'us-central1-b', 'us-central1-a',
                       'ZONE_RESOURCE_POOL_EXHAUSTED_WITH_DETAILS'):
            assert needle in loud[-1].message
        assert not any('created' in r.message and r.levelno == logging.INFO and 'gcp-runner' in r.message
                       for r in caplog.records)

    def test_default_floor_walks_all_the_way_to_two_cores(self, clients):
        instances, _ = clients
        instances.insert.side_effect = [_wrap(_recorded_exhausted_operation()) for _ in range(15)] + [_ok_operation()]
        client = GCloudClient()

        client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-auto-compute-16', 'o/r')

        attempts = _attempts(instances)
        assert len(attempts) == 16
        assert attempts[-1] == ('general-2', 'us-central1-a')
        assert _landed(instances).labels['gha-rung'] == 'general-2'

    def test_general_tier_never_tries_compute(self, clients):
        instances, _ = clients
        instances.insert.side_effect = [_wrap(_recorded_exhausted_operation())] * 2 + [_ok_operation()]
        client = GCloudClient()

        client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-auto-general-4', 'o/r')

        assert _attempts(instances) == [('general-4', 'us-central1-b'), ('general-4', 'us-central1-a'),
                                        ('general-2', 'us-central1-b')]

    def test_non_capacity_error_stops_the_ladder(self, clients):
        instances, _ = clients
        instances.insert.side_effect = [_wrap(_operation_with_error('INVALID_FIELD_VALUE', 'bad'))]
        client = GCloudClient()

        with pytest.raises(InstanceCreationError):
            client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-auto-compute-16', 'o/r')

        assert len(_attempts(instances)) == 1

    def test_missing_rung_template_is_skipped_with_warning(self, clients, caplog):
        instances, templates = clients
        templates.list.return_value = [t for t in ALL_RUNG_TEMPLATES if 'compute-16' not in t.name]
        instances.insert.side_effect = [_ok_operation()]
        client = GCloudClient()

        with caplog.at_level(logging.WARNING, logger='app.clients.gcloud_client'):
            client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-auto-compute-16', 'o/r')

        assert _attempts(instances) == [('general-16', 'us-central1-b')]
        assert any('compute-16' in r.message and 'no matching instance template' in r.message.lower()
                   for r in caplog.records)

    def test_no_rung_template_at_all_returns_none(self, clients):
        instances, templates = clients
        templates.list.return_value = []
        client = GCloudClient()

        assert client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-auto-general-2', 'o/r') is None
        instances.insert.assert_not_called()

    def test_invalid_auto_label_raises_before_any_api_call(self, clients):
        instances, _ = clients
        with pytest.raises(InvalidAutoLabel):
            GCloudClient().create_runner_instance('tok', 'https://github.com/o/r', 'gcp-auto-compute-32', 'o/r')
        instances.insert.assert_not_called()

    def test_explicit_label_is_unaffected(self, clients):
        instances, _ = clients
        instances.insert.side_effect = [_ok_operation()]
        client = GCloudClient()

        name = client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-ubuntu-24.04', 'o/r', job_id=3)

        assert name == 'gcp-runner-3'
        request = instances.insert.call_args.kwargs['request']
        assert request.source_instance_template.endswith('gcp-ubuntu-24-04-20260909120000')
        resource = request.instance_resource
        assert 'gha-rung' not in resource.labels
        assert resource.labels['gha-runner'] == 'gcp-ubuntu-24-04', 'label values are sanitised for GCE'
        assert 'gcp-auto' not in _startup_script(resource)
