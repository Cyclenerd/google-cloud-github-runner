"""
Keeps the Terraform alert policies in step with the heartbeat the reconciler actually writes.

The log-based metrics in gcp/monitoring.tf filter on the heartbeat's event key and extract the
oldest_queued_job_age_seconds field; if either name changes in the app without the Terraform
following, the alerts go silent. These tests read the .tf file and check the contract.
"""
import json
import os
import re

from app.services.reconcile_service import HEARTBEAT_EVENT, HEARTBEAT_MARKER, emit_structured

TF_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'gcp', 'monitoring.tf')
VARIABLES_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'gcp', 'variables.tf')


def _tf():
    with open(TF_PATH) as fh:
        return fh.read()


class TestHeartbeatContract:
    def test_metric_filters_match_the_heartbeat_event(self):
        tf = _tf()
        assert f'jsonPayload.event=\\"{HEARTBEAT_EVENT}\\"' in tf

    def test_age_metric_extracts_the_field_the_heartbeat_writes(self, capsys):
        emit_structured(HEARTBEAT_EVENT, f'{HEARTBEAT_MARKER} run_id=t', run_id='t', oldest_queued_job_age_seconds=1234)
        line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert line['event'] == HEARTBEAT_EVENT
        field = re.search(r'value_extractor\s*=\s*"EXTRACT\(jsonPayload\.(\w+)\)"', _tf()).group(1)
        assert field in line, f'Terraform extracts jsonPayload.{field} but the heartbeat does not carry it'
        assert line[field] == 1234

    def test_both_policies_exist_without_notification_channels(self):
        tf = _tf()
        policies = re.findall(r'resource "google_monitoring_alert_policy" "([^"]+)"', tf)
        assert sorted(policies) == ['github-runners-reconciler-heartbeat-missing', 'github-runners-stuck-job']
        assert tf.count('notification_channels = []') == 2
        assert 'condition_absent' in tf and 'condition_threshold' in tf

    def test_thresholds_come_from_variables_with_sane_defaults(self):
        variables = open(VARIABLES_PATH).read()
        heartbeat = re.search(r'variable "github_runners_alert_heartbeat_missing_seconds" \{.*?default\s*=\s*(\d+)',
                              variables, re.S)
        stuck = re.search(r'variable "github_runners_alert_stuck_job_seconds" \{.*?default\s*=\s*(\d+)', variables, re.S)
        assert int(heartbeat.group(1)) == 900, 'no completed pass in 15 minutes'
        assert int(stuck.group(1)) == 1800, 'a job queued for more than 30 minutes'
        tf = _tf()
        assert 'var.github_runners_alert_heartbeat_missing_seconds' in tf
        assert 'threshold_value = var.github_runners_alert_stuck_job_seconds' in tf

    def test_synthetic_entry_from_the_drill_script_matches_the_filter(self):
        """The drill writes the same shape with gcloud logging write; keep the two in step."""
        script = open(os.path.join(os.path.dirname(TF_PATH), '..', 'tools', 'alert-drill.sh')).read()
        assert f'"event": "{HEARTBEAT_EVENT}"' in script
        assert '"oldest_queued_job_age_seconds"' in script
        assert '"type": "cloud_run_revision"' in script, 'the alert conditions require this resource type'
        assert _tf().count('resource.type=\\"cloud_run_revision\\"') == 2
