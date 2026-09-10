"""
Tests for zone fallback inside the region and cross-zone instance deletion.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest
from google.cloud import compute_v1

from app.clients import gcloud_client
from app.clients.gcloud_client import GCloudClient, InstanceCreationError, ZoneCapacityError
from tests.unit.test_gcloud_client_operation_wait import (
    TEMPLATE_SELF_LINK,
    _operation_with_error,
    _recorded_exhausted_operation,
    _wrap,
)

REGION_LINK = 'https://www.googleapis.com/compute/v1/projects/test-project/regions/us-central1'


def _zone(name, region=REGION_LINK, status='UP'):
    zone = MagicMock()
    zone.name = name
    zone.region = region
    zone.status = status
    return zone


def _ok_operation():
    operation = MagicMock()
    operation.name = 'operation-ok'
    operation.result.return_value = None
    operation.error.errors = []
    return operation


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
    monkeypatch.setenv('GOOGLE_CLOUD_ZONE', 'us-central1-b')


@pytest.fixture
def clients(env):
    with patch.object(gcloud_client.compute_v1, 'InstancesClient') as instances, \
            patch.object(gcloud_client.compute_v1, 'RegionInstanceTemplatesClient') as templates, \
            patch.object(gcloud_client.compute_v1, 'ZonesClient') as zones:
        template = MagicMock()
        template.name = 'gcp-ubuntu-24-04-12345678901234'
        template.self_link = TEMPLATE_SELF_LINK
        templates.return_value.list.return_value = [template]
        # Unsorted on purpose, with a zone from another region and a DOWN zone mixed in.
        zones.return_value.list.return_value = [
            _zone('us-central1-f'),
            _zone('us-east1-b', region=REGION_LINK.replace('us-central1', 'us-east1')),
            _zone('us-central1-c'),
            _zone('us-central1-a'),
            _zone('us-central1-b'),
            _zone('us-central1-d', status='DOWN'),
        ]
        yield instances.return_value, templates.return_value, zones.return_value


def _inserted_zones(instances):
    return [call.kwargs['request'].zone for call in instances.insert.call_args_list]


class TestCandidateZones:
    def test_configured_zone_first_then_stable_order_within_region(self, clients):
        client = GCloudClient()
        assert client.candidate_zones() == ['us-central1-b', 'us-central1-a', 'us-central1-c', 'us-central1-f']

    def test_zone_listing_failure_falls_back_to_configured_zone(self, clients, caplog):
        _, _, zones = clients
        zones.list.side_effect = RuntimeError('zones unavailable')
        client = GCloudClient()
        with caplog.at_level(logging.WARNING, logger='app.clients.gcloud_client'):
            assert client.candidate_zones() == ['us-central1-b']
        assert any('zones unavailable' in r.message for r in caplog.records)


class TestZoneFallback:
    def test_exhausted_zone_b_lands_in_next_zone_and_is_labelled(self, clients, caplog):
        instances, _, _ = clients
        instances.insert.side_effect = [_wrap(_recorded_exhausted_operation()), _ok_operation()]
        client = GCloudClient()

        with caplog.at_level(logging.INFO, logger='app.clients.gcloud_client'):
            name = client.create_runner_instance(
                'tok', 'https://github.com/o/r', 'gcp-ubuntu-24.04', 'o/r', delivery_id='d-fb'
            )

        assert name.startswith('gcp-runner-')
        assert _inserted_zones(instances) == ['us-central1-b', 'us-central1-a']
        landed = instances.insert.call_args_list[1].kwargs['request'].instance_resource
        assert landed.name == name
        assert landed.labels['gha-zone'] == 'us-central1-a'
        assert landed.labels['gha-owner'] == 'o'
        assert any('us-central1-a' in r.message and 'd-fb' in r.message and 'created' in r.message
                   for r in caplog.records)
        assert any('ZONE_RESOURCE_POOL_EXHAUSTED_WITH_DETAILS' in r.message for r in caplog.records)

    def test_all_zones_exhausted_fails_loudly(self, clients, caplog):
        instances, _, _ = clients
        instances.insert.side_effect = [_wrap(_recorded_exhausted_operation()) for _ in range(4)]
        client = GCloudClient()

        with caplog.at_level(logging.ERROR, logger='app.clients.gcloud_client'):
            with pytest.raises(ZoneCapacityError) as excinfo:
                client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-ubuntu-24.04',
                                              delivery_id='d-all')

        assert _inserted_zones(instances) == ['us-central1-b', 'us-central1-a', 'us-central1-c', 'us-central1-f']
        assert 'us-central1-f' in str(excinfo.value)
        error_logs = [r for r in caplog.records if r.levelno == logging.ERROR and 'd-all' in r.message]
        assert error_logs, 'expected an ERROR log naming the tried zones'
        for zone in ('us-central1-b', 'us-central1-a', 'us-central1-c', 'us-central1-f'):
            assert zone in error_logs[-1].message

    def test_non_capacity_error_does_not_fall_back(self, clients):
        instances, _, _ = clients
        instances.insert.side_effect = [_wrap(_operation_with_error('INVALID_FIELD_VALUE', 'bad'))]
        client = GCloudClient()

        with pytest.raises(InstanceCreationError):
            client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-ubuntu-24.04')

        assert _inserted_zones(instances) == ['us-central1-b']

    def test_success_in_first_zone_does_not_touch_other_zones(self, clients):
        instances, _, _ = clients
        instances.insert.side_effect = [_ok_operation()]
        client = GCloudClient()

        client.create_runner_instance('tok', 'https://github.com/o/r', 'gcp-ubuntu-24.04')

        assert _inserted_zones(instances) == ['us-central1-b']
        resource = instances.insert.call_args_list[0].kwargs['request'].instance_resource
        assert resource.labels['gha-zone'] == 'us-central1-b'


def _aggregated(found_in=None, name='gcp-runner-abc'):
    """Build an aggregated_list result: list of (zone_key, InstancesScopedList)."""
    result = []
    for zone in ('us-central1-a', 'us-central1-b', 'us-central1-c'):
        scoped = compute_v1.InstancesScopedList()
        if zone == found_in:
            scoped.instances = [compute_v1.Instance(name=name, zone=f'{REGION_LINK[:-19]}zones/{zone}')]
        result.append((f'zones/{zone}', scoped))
    return result


class TestCrossZoneDelete:
    def test_delete_finds_instance_in_other_zone(self, clients, caplog):
        instances, _, _ = clients
        instances.aggregated_list.return_value = _aggregated(found_in='us-central1-c')
        client = GCloudClient()

        with caplog.at_level(logging.INFO, logger='app.clients.gcloud_client'):
            client.delete_runner_instance('gcp-runner-abc', delivery_id='d-del')

        request = instances.aggregated_list.call_args.kwargs['request']
        assert request.project == 'test-project'
        instances.delete.assert_called_once_with(project='test-project', zone='us-central1-c', instance='gcp-runner-abc')
        assert any('us-central1-c' in r.message and 'd-del' in r.message for r in caplog.records)

    def test_delete_missing_instance_logs_warning_and_does_not_raise(self, clients, caplog):
        instances, _, _ = clients
        instances.aggregated_list.return_value = _aggregated(found_in=None)
        client = GCloudClient()

        with caplog.at_level(logging.WARNING, logger='app.clients.gcloud_client'):
            assert client.delete_runner_instance('gcp-runner-abc', delivery_id='d-miss') is None

        instances.delete.assert_not_called()
        assert any('not found' in r.message and 'd-miss' in r.message for r in caplog.records)

    def test_delete_falls_back_to_configured_zone_when_lookup_fails(self, clients, caplog):
        instances, _, _ = clients
        instances.aggregated_list.side_effect = RuntimeError('aggregatedList denied')
        client = GCloudClient()

        with caplog.at_level(logging.WARNING, logger='app.clients.gcloud_client'):
            client.delete_runner_instance('gcp-runner-abc')

        instances.delete.assert_called_once_with(project='test-project', zone='us-central1-b', instance='gcp-runner-abc')
        assert any('aggregatedList denied' in r.message for r in caplog.records)
