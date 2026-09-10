"""
Decision-table tests for the reconciler.

Each case fixes the GitHub view (jobs, runners), the Compute view (VMs with ages) and asserts
what the pass creates, deletes, keeps or skips. Both directions are covered: the reconciler
must create when it should and must never delete a VM that is running a job.
"""
import datetime
import json

import pytest

from app.services.reconcile_service import ReconcileService, RECONCILE_NAME_SUFFIX, template_label_for

NOW = datetime.datetime(2026, 9, 9, 12, 0, 0, tzinfo=datetime.timezone.utc)
ORG_REPO = {
    'full_name': 'example-org/example-repo',
    'html_url': 'https://github.com/example-org/example-repo',
    'owner': {'login': 'example-org', 'type': 'Organization', 'html_url': 'https://github.com/example-org'},
}
USER_REPO = {
    'full_name': 'octocat/hello',
    'html_url': 'https://github.com/octocat/hello',
    'owner': {'login': 'octocat', 'type': 'User', 'html_url': 'https://github.com/octocat'},
}
LABEL = 'gcp-ubuntu-24-04-std16'


def minutes_ago(minutes):
    return NOW - datetime.timedelta(minutes=minutes)


def job(job_id, status, age_minutes=15, runner_name='', labels=(LABEL,), conclusion=None):
    return {
        'id': job_id,
        'name': f'job-{job_id}',
        'status': status,
        'conclusion': conclusion,
        'labels': list(labels),
        'runner_name': runner_name,
        'created_at': minutes_ago(age_minutes).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'run_id': 1,
    }


def vm(name, age_minutes=15, job_id=None, status='RUNNING', owner='example-org', repo='example-repo', zone='us-central1-b'):
    labels = {'gha-owner': owner, 'gha-repo': repo, 'gha-runner': LABEL, 'gha-zone': zone}
    if job_id is not None:
        labels['gha-job-id'] = str(job_id)
    return {'name': name, 'zone': zone, 'status': status, 'labels': labels, 'created_at': minutes_ago(age_minutes)}


def runner(name, busy=False, status='online', runner_id=None):
    return {'id': runner_id or abs(hash(name)) % 100000, 'name': name, 'status': status, 'busy': busy}


class FakeGitHub:
    def __init__(self, repos=None, jobs=None, runners=None, fresh=None):
        self.repos = repos if repos is not None else [ORG_REPO]
        self.jobs = jobs or {}                  # repo full_name -> list of jobs
        self.runners = runners or {}            # ('org', login) / ('repo', full_name) -> list of runners
        self.fresh = fresh or {}                # job id -> fresh job dict, None (404) or Exception
        self.deleted_runners = []
        self.delete_runner_error = None
        self.list_jobs_error = {}
        self.list_runners_error = {}
        self.calls = []

    def get_installation_access_token(self):
        return 'tok'

    def list_installation_repositories(self, token=None):
        return self.repos

    def list_workflow_jobs(self, repo_name, token=None):
        if repo_name in self.list_jobs_error:
            raise self.list_jobs_error[repo_name]
        return list(self.jobs.get(repo_name, []))

    def get_workflow_job(self, repo_name, job_id, token=None):
        self.calls.append(('get_workflow_job', repo_name, str(job_id)))
        if str(job_id) in self.fresh:
            value = self.fresh[str(job_id)]
            if isinstance(value, Exception):
                raise value
            return value
        for jobs in self.jobs.values():
            for j in jobs:
                if str(j['id']) == str(job_id):
                    return j
        return None

    def list_runners(self, org_name=None, repo_name=None, token=None):
        scope = ('org', org_name) if org_name else ('repo', repo_name)
        self.calls.append(('list_runners', scope))
        if scope in self.list_runners_error:
            raise self.list_runners_error[scope]
        return list(self.runners.get(scope, []))

    def delete_runner(self, runner_id, org_name=None, repo_name=None, token=None):
        scope = ('org', org_name) if org_name else ('repo', repo_name)
        self.calls.append(('delete_runner', scope, runner_id))
        if self.delete_runner_error:
            raise self.delete_runner_error
        self.deleted_runners.append((scope, runner_id))
        return True


class FakeGCloud:
    def __init__(self, vms=None, templates_for=None):
        self.vms = vms or []
        self.deleted = []
        self.delete_error = None
        self.templates_for = templates_for  # None = every label has a template
        self.template_list_calls = 0

    def list_runner_instances(self):
        return list(self.vms)

    def list_templates(self):
        self.template_list_calls += 1
        return ['templates']

    def has_template_for(self, label, templates=None):
        assert templates == ['templates'], 'must reuse the per-pass template list'
        return True if self.templates_for is None else label in self.templates_for

    def delete_runner_instance(self, name, delivery_id=None, zone=None):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append((name, zone))
        return zone


class FakeProvisioner:
    def __init__(self, error_for=()):
        self.calls = []
        self.error_for = set(str(j) for j in error_for)

    def provision_runner(self, template_name, repo_url, repo_owner_url, repo_name, org_name,
                         job_id=None, delivery_id=None, name_suffix=''):
        self.calls.append({'template': template_name, 'repo_url': repo_url, 'owner_url': repo_owner_url,
                           'repo_name': repo_name, 'org_name': org_name, 'job_id': job_id,
                           'delivery_id': delivery_id, 'name_suffix': name_suffix})
        if str(job_id) in self.error_for:
            raise RuntimeError(f'boom {job_id}')
        return f'gcp-runner-{job_id}{name_suffix}'


def run_pass(github, gcloud, provisioner=None, dry_run=False, **kwargs):
    provisioner = provisioner or FakeProvisioner()
    service = ReconcileService(github_client=github, gcloud_client=gcloud, webhook_service=provisioner,
                               stuck_minutes=10, max_creates=20, create_workers=2, now=NOW, **kwargs)
    return service.run(dry_run=dry_run), provisioner


def reasons(report, key):
    return [entry['reason'] for entry in report[key]]


# ---------------------------------------------------------------------------
# Delete direction: table of (job state, VM age, runner state) -> decision
# ---------------------------------------------------------------------------

class TestDeleteDecisions:
    def test_young_vm_is_never_touched_even_without_a_job(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'queued')]})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=5, job_id=1)])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == []
        assert 'younger than 10 minutes' in reasons(report, 'kept')[0]

    def test_vm_running_its_own_job_is_kept(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'in_progress', runner_name='gcp-runner-1')]},
                            runners={('org', 'example-org'): [runner('gcp-runner-1', busy=True)]})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=120, job_id=1)])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == []
        assert github.deleted_runners == []
        assert 'in_progress job on this runner name' in reasons(report, 'kept')[0]

    def test_vm_labelled_for_cancelled_job_but_running_another_job_is_kept(self):
        """An idle ephemeral runner takes the next queued job, not the one it was created for."""
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [
            job(1, 'completed', conclusion='cancelled'),
            job(2, 'in_progress', runner_name='gcp-runner-1'),
        ]})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=30, job_id=1)])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == []
        assert 'in_progress job on this runner name' in reasons(report, 'kept')[0]

    def test_busy_runner_is_kept_even_if_job_list_lags(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'completed', conclusion='success')]},
                            runners={('org', 'example-org'): [runner('gcp-runner-1', busy=True)]})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=30, job_id=1)])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == []
        assert 'busy' in reasons(report, 'kept')[0]

    def test_fresh_recheck_in_progress_overrides_stale_listing(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'queued')]},
                            fresh={'1': job(1, 'in_progress', runner_name='gcp-runner-1')})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=30, job_id=1)])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == []
        assert 're-checked as in_progress' in reasons(report, 'kept')[0]
        assert ('get_workflow_job', 'example-org/example-repo', '1') in github.calls

    def test_completed_job_without_completed_webhook_is_deleted(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'completed', conclusion='success')]})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=30, job_id=1, zone='us-central1-c')])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == [('gcp-runner-1', 'us-central1-c')]
        assert report['deleted'][0]['reason'] == 'job is completed/success'
        assert report['deleted'][0]['job_id'] == '1'
        assert report['deleted'][0]['zone'] == 'us-central1-c'

    def test_job_missing_on_github_is_deleted(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: []})
        gcloud = FakeGCloud([vm('gcp-runner-9', age_minutes=30, job_id=9)])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == [('gcp-runner-9', 'us-central1-b')]
        assert 'not found' in report['deleted'][0]['reason']

    def test_runner_never_registered_is_deleted_and_job_not_recreated_this_pass(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'queued', age_minutes=30)]})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=30, job_id=1)])
        report, provisioner = run_pass(github, gcloud)
        assert gcloud.deleted == [('gcp-runner-1', 'us-central1-b')]
        assert 'never registered' in report['deleted'][0]['reason']
        assert provisioner.calls == []
        assert any('deleted in this pass' in r for r in reasons(report, 'skipped'))

    def test_registered_online_runner_with_queued_job_is_kept(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'queued', age_minutes=30)]},
                            runners={('org', 'example-org'): [runner('gcp-runner-1')]})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=30, job_id=1)])
        report, provisioner = run_pass(github, gcloud)
        assert gcloud.deleted == []
        assert 'registered and online' in reasons(report, 'kept')[0]
        assert provisioner.calls == []

    def test_orphan_without_job_label_and_without_runner_is_deleted(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: []})
        gcloud = FakeGCloud([vm('gcp-runner-old', age_minutes=45)])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == [('gcp-runner-old', 'us-central1-b')]
        assert 'no job label and no registered runner' in report['deleted'][0]['reason']

    def test_idle_registered_runner_is_deregistered_before_the_vm_is_deleted(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'completed', conclusion='cancelled')]},
                            runners={('org', 'example-org'): [runner('gcp-runner-1', runner_id=77)]})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=30, job_id=1)])
        report, _ = run_pass(github, gcloud)
        assert github.deleted_runners == [(('org', 'example-org'), 77)]
        assert gcloud.deleted == [('gcp-runner-1', 'us-central1-b')]
        delete_calls = [c for c in github.calls if c[0] == 'delete_runner']
        assert delete_calls, 'runner must be removed from GitHub before the VM goes away'

    def test_vm_is_not_deleted_when_github_refuses_to_remove_the_runner(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'completed', conclusion='success')]},
                            runners={('org', 'example-org'): [runner('gcp-runner-1')]})
        github.delete_runner_error = RuntimeError('422 runner is busy')
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=30, job_id=1)])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == []
        assert any('runner removal failed' in r for r in reasons(report, 'skipped'))

    def test_recheck_failure_skips_the_vm(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'completed')]},
                            fresh={'1': RuntimeError('GitHub 502')})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=30, job_id=1)])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == []
        assert any('could not re-check' in r for r in reasons(report, 'skipped'))

    def test_stopping_vm_is_ignored(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: []})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=60, job_id=1, status='STOPPING')])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == []
        assert report['live_vms'] == 0

    def test_job_listing_failure_only_protects_that_repository(self):
        """Review: one broken repository must not disable deletions for the other 86."""
        broken = {**ORG_REPO, 'full_name': 'example-org/broken', 'html_url': 'https://github.com/example-org/broken'}
        github = FakeGitHub(repos=[ORG_REPO, broken], jobs={ORG_REPO['full_name']: []})
        github.list_jobs_error[broken['full_name']] = RuntimeError('403 disabled')
        gcloud = FakeGCloud([vm('gcp-runner-old', age_minutes=45),
                             vm('gcp-runner-broken', age_minutes=45, repo='broken')])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == [('gcp-runner-old', 'us-central1-b')]
        assert any(s.get('vm') == 'gcp-runner-broken' and 'could not be listed' in s['reason'] for s in report['skipped'])
        assert not any(s.get('phase') == 'delete' for s in report['skipped'])
        assert report['errors'] and 'list jobs' in report['errors'][0]['error']

    def test_runner_listing_failure_disables_the_delete_phase(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: []})
        github.list_runners_error[('org', 'example-org')] = RuntimeError('403')
        gcloud = FakeGCloud([vm('gcp-runner-old', age_minutes=45)])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == []
        assert any(s.get('phase') == 'delete' for s in report['skipped'])

    def test_vm_of_unknown_repository_is_skipped(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: []})
        gcloud = FakeGCloud([vm('gcp-runner-x', age_minutes=45, owner='someone', repo='else')])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == []
        assert any('do not match any installed repository' in r for r in reasons(report, 'skipped'))

    def test_user_owned_repository_uses_repository_level_runners(self):
        github = FakeGitHub(repos=[USER_REPO], jobs={USER_REPO['full_name']: [job(5, 'completed')]},
                            runners={('repo', 'octocat/hello'): [runner('gcp-runner-5', runner_id=5)]})
        gcloud = FakeGCloud([vm('gcp-runner-5', age_minutes=30, job_id=5, owner='octocat', repo='hello')])
        report, _ = run_pass(github, gcloud)
        assert ('list_runners', ('repo', 'octocat/hello')) in github.calls
        assert github.deleted_runners == [(('repo', 'octocat/hello'), 5)]
        assert gcloud.deleted == [('gcp-runner-5', 'us-central1-b')]

    def test_vm_delete_failure_is_reported(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'completed')]})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=30, job_id=1)])
        gcloud.delete_error = RuntimeError('compute 500')
        report, _ = run_pass(github, gcloud)
        assert report['deleted'] == []
        assert any('compute 500' in e['error'] for e in report['errors'])

    def test_dry_run_deletes_nothing(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'completed')]},
                            runners={('org', 'example-org'): [runner('gcp-runner-1')]})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=30, job_id=1)])
        report, _ = run_pass(github, gcloud, dry_run=True)
        assert gcloud.deleted == []
        assert github.deleted_runners == []
        assert report['deleted'][0]['dry_run'] is True


# ---------------------------------------------------------------------------
# Create direction
# ---------------------------------------------------------------------------

class TestCreateDecisions:
    def test_stuck_queued_job_without_vm_gets_one(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(42, 'queued', age_minutes=15)]})
        gcloud = FakeGCloud([])
        report, provisioner = run_pass(github, gcloud)
        assert len(provisioner.calls) == 1
        call = provisioner.calls[0]
        assert call['template'] == LABEL
        assert call['job_id'] == 42
        assert call['name_suffix'] == RECONCILE_NAME_SUFFIX
        assert call['org_name'] == 'example-org'
        assert call['repo_name'] == 'example-org/example-repo'
        assert call['owner_url'] == 'https://github.com/example-org'
        assert report['created'][0]['vm'] == 'gcp-runner-42-r'

    def test_recently_queued_job_is_left_to_the_webhook(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(42, 'queued', age_minutes=2)]})
        report, provisioner = run_pass(github, FakeGCloud([]))
        assert provisioner.calls == []
        assert report['created'] == []

    def test_job_with_a_vm_is_not_provisioned_twice(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(42, 'queued', age_minutes=15)]})
        gcloud = FakeGCloud([vm('gcp-runner-42', age_minutes=1, job_id=42)])
        report, provisioner = run_pass(github, gcloud)
        assert provisioner.calls == []

    def test_job_on_non_gcp_label_is_ignored(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(42, 'queued', age_minutes=15, labels=('ubuntu-latest',))]})
        report, provisioner = run_pass(github, FakeGCloud([]))
        assert provisioner.calls == []
        assert report['queued_jobs'] == 0

    def test_dependabot_label_is_provisioned(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(43, 'queued', age_minutes=15, labels=('dependabot',))]})
        report, provisioner = run_pass(github, FakeGCloud([]))
        assert provisioner.calls[0]['template'] == 'dependabot'

    def test_user_repository_provisions_at_repository_scope(self):
        github = FakeGitHub(repos=[USER_REPO], jobs={USER_REPO['full_name']: [job(7, 'queued', age_minutes=15)]})
        report, provisioner = run_pass(github, FakeGCloud([]))
        assert provisioner.calls[0]['org_name'] is None
        assert provisioner.calls[0]['repo_url'] == 'https://github.com/octocat/hello'

    def test_creations_are_capped_per_pass_oldest_first(self):
        jobs = [job(i, 'queued', age_minutes=10 + i) for i in range(1, 6)]
        github = FakeGitHub(jobs={ORG_REPO['full_name']: jobs})
        provisioner = FakeProvisioner()
        service = ReconcileService(github_client=github, gcloud_client=FakeGCloud([]), webhook_service=provisioner,
                                   stuck_minutes=10, max_creates=2, create_workers=1, now=NOW)
        report = service.run()
        assert sorted(c['job_id'] for c in provisioner.calls) == [4, 5]
        assert len([s for s in report['skipped'] if 'deferred' in s['reason']]) == 3

    def test_one_failed_creation_does_not_stop_the_others(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'queued', age_minutes=15),
                                                          job(2, 'queued', age_minutes=15)]})
        report, provisioner = run_pass(github, FakeGCloud([]), provisioner=FakeProvisioner(error_for=[1]))
        assert sorted(c['job_id'] for c in provisioner.calls) == [1, 2]
        assert [c['job_id'] for c in report['created']] == ['2']
        assert any('boom 1' in e['error'] for e in report['errors'])

    def test_no_template_is_reported_as_skipped(self):
        class NoTemplate(FakeProvisioner):
            def provision_runner(self, *args, **kwargs):
                super().provision_runner(*args, **kwargs)
                return None
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'queued', age_minutes=15)]})
        report, _ = run_pass(github, FakeGCloud([]), provisioner=NoTemplate())
        assert report['created'] == []
        assert any('no matching instance template' in r for r in reasons(report, 'skipped'))

    def test_dry_run_creates_nothing(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'queued', age_minutes=15)]})
        report, provisioner = run_pass(github, FakeGCloud([]), dry_run=True)
        assert provisioner.calls == []
        assert report['created'][0]['dry_run'] is True

    def test_creation_still_happens_when_a_listing_fails(self):
        github = FakeGitHub(repos=[ORG_REPO, USER_REPO],
                            jobs={ORG_REPO['full_name']: [job(1, 'queued', age_minutes=15)]})
        github.list_jobs_error[USER_REPO['full_name']] = RuntimeError('503')
        report, provisioner = run_pass(github, FakeGCloud([vm('gcp-runner-old', age_minutes=45)]))
        assert [c['job_id'] for c in provisioner.calls] == [1]


class TestHelpers:
    @pytest.mark.parametrize('labels,expected', [
        (['gcp-ubuntu-24-04-std16'], 'gcp-ubuntu-24-04-std16'),
        (['self-hosted', 'gcp-ubuntu-24.04'], 'gcp-ubuntu-24.04'),
        (['Dependabot'], 'Dependabot'),
        (['ubuntu-latest'], None),
        ([], None),
        (None, None),
    ])
    def test_template_label_matches_webhook_rule(self, labels, expected):
        assert template_label_for(labels) == expected

    def test_env_defaults(self, monkeypatch):
        monkeypatch.setenv('RECONCILE_STUCK_MINUTES', '7')
        monkeypatch.setenv('RECONCILE_MAX_CREATES', 'oops')
        service = ReconcileService(github_client=FakeGitHub(), gcloud_client=FakeGCloud(), webhook_service=FakeProvisioner())
        assert service.stuck_minutes == 7
        assert service.max_creates == 20


class TestRepositoryCoverage:
    def test_every_installed_repository_is_scanned_without_configuration(self):
        github = FakeGitHub(repos=[ORG_REPO, USER_REPO], jobs={})
        report, _ = run_pass(github, FakeGCloud([]))
        assert report['repositories'] == ['example-org/example-repo', 'octocat/hello']

    def test_queued_job_in_a_second_repository_is_provisioned(self):
        second = {**ORG_REPO, 'full_name': 'example-org/second', 'html_url': 'https://github.com/example-org/second'}
        github = FakeGitHub(repos=[ORG_REPO, second],
                            jobs={ORG_REPO['full_name']: [], 'example-org/second': [job(7, 'queued', age_minutes=15)]})
        report, provisioner = run_pass(github, FakeGCloud([]))
        assert [c['repo_name'] for c in provisioner.calls] == ['example-org/second']
        assert report['created'][0]['repo'] == 'example-org/second'

    def test_exclude_list_drops_named_repositories_only(self, monkeypatch):
        monkeypatch.setenv('RECONCILE_EXCLUDE_REPOSITORIES', 'OCTOCAT/hello, other/thing')
        github = FakeGitHub(repos=[ORG_REPO, USER_REPO],
                            jobs={USER_REPO['full_name']: [job(1, 'queued', age_minutes=15)]})
        service = ReconcileService(github_client=github, gcloud_client=FakeGCloud(), webhook_service=FakeProvisioner(),
                                   now=NOW)
        report = service.run()
        assert report['repositories'] == ['example-org/example-repo']
        assert service.webhook_service.calls == []

    def test_excluded_repository_vms_are_left_alone(self, monkeypatch):
        """Excluded means neither provisioned for nor cleaned up by the reconciler."""
        monkeypatch.setenv('RECONCILE_EXCLUDE_REPOSITORIES', 'example-org/example-repo')
        github = FakeGitHub(repos=[ORG_REPO, USER_REPO], jobs={})
        gcloud = FakeGCloud([vm('gcp-runner-x', age_minutes=45, job_id=9)])
        service = ReconcileService(github_client=github, gcloud_client=gcloud, webhook_service=FakeProvisioner(), now=NOW)
        report = service.run()
        assert gcloud.deleted == []
        assert any(s.get('vm') == 'gcp-runner-x' and 'excluded' in s['reason'] for s in report['skipped'])

    def test_exclude_entry_matching_nothing_is_warned_about(self, caplog):
        github = FakeGitHub(repos=[ORG_REPO], jobs={})
        with caplog.at_level('WARNING', logger='app.services.reconcile_service'):
            run_pass(github, FakeGCloud([]), exclude_repositories='example-org/old-name')
        assert any('old-name' in r.message and 'cannot see' in r.message for r in caplog.records)

    def test_archived_and_disabled_repositories_are_not_scanned(self):
        archived = {**USER_REPO, 'full_name': 'octocat/archived', 'archived': True}
        disabled = {**USER_REPO, 'full_name': 'octocat/disabled', 'disabled': True}
        github = FakeGitHub(repos=[ORG_REPO, archived, disabled], jobs={})
        report, _ = run_pass(github, FakeGCloud([]))
        assert report['repositories'] == ['example-org/example-repo']

    def test_include_list_no_longer_exists(self, monkeypatch):
        monkeypatch.setenv('RECONCILE_REPOSITORIES', 'octocat/hello')
        github = FakeGitHub(repos=[ORG_REPO, USER_REPO], jobs={})
        report, _ = run_pass(github, FakeGCloud([]))
        assert report['repositories'] == ['example-org/example-repo', 'octocat/hello'], 'the old include list is ignored'

    def test_creation_budget_is_shared_round_robin_across_repositories(self):
        """A 100-job fan-out in one repository must not starve a single job in another."""
        fanout = {**ORG_REPO, 'full_name': 'example-org/fanout', 'html_url': 'https://github.com/example-org/fanout'}
        quiet = {**ORG_REPO, 'full_name': 'example-org/quiet', 'html_url': 'https://github.com/example-org/quiet'}
        github = FakeGitHub(repos=[fanout, quiet], jobs={
            'example-org/fanout': [job(100 + i, 'queued', age_minutes=30) for i in range(30)],
            'example-org/quiet': [job(1, 'queued', age_minutes=12)],   # younger than every fan-out job
        })
        provisioner = FakeProvisioner()
        service = ReconcileService(github_client=github, gcloud_client=FakeGCloud([]), webhook_service=provisioner,
                                   stuck_minutes=10, max_creates=10, create_workers=1, now=NOW)
        report = service.run()
        created = [c['repo_name'] for c in provisioner.calls]
        assert created.count('example-org/quiet') == 1
        assert created.count('example-org/fanout') == 9
        assert len([s for s in report['skipped'] if 'deferred' in s['reason']]) == 21


class TestLabelMatching:
    def test_repository_with_dot_in_name_matches_sanitised_labels(self):
        dotted = {
            'full_name': 'octocat/hello.js',
            'html_url': 'https://github.com/octocat/hello.js',
            'owner': {'login': 'octocat', 'type': 'User', 'html_url': 'https://github.com/octocat'},
        }
        github = FakeGitHub(repos=[dotted], jobs={'octocat/hello.js': [job(5, 'completed')]},
                            runners={('repo', 'octocat/hello.js'): []})
        gcloud = FakeGCloud([vm('gcp-runner-5', age_minutes=30, job_id=5, owner='octocat', repo='hello-js')])
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == [('gcp-runner-5', 'us-central1-b')]
        assert ('get_workflow_job', 'octocat/hello.js', '5') in github.calls


class TestReviewFindings:
    def test_jobs_without_a_template_do_not_consume_the_creation_budget(self):
        """Review finding 1: 25 old jobs on a typo label must not starve one real stuck job."""
        typo = [job(100 + i, 'queued', age_minutes=60, labels=('gcp-typo',)) for i in range(25)]
        real = job(999, 'queued', age_minutes=15)
        github = FakeGitHub(jobs={ORG_REPO['full_name']: typo + [real]})
        gcloud = FakeGCloud([], templates_for={LABEL})
        provisioner = FakeProvisioner()
        service = ReconcileService(github_client=github, gcloud_client=gcloud, webhook_service=provisioner,
                                   stuck_minutes=10, max_creates=20, create_workers=1, now=NOW)
        report = service.run()
        assert [c['job_id'] for c in provisioner.calls] == [999]
        assert len([s for s in report['skipped'] if 'no matching instance template' in s['reason']]) == 25
        assert gcloud.template_list_calls == 1, 'templates are listed once per pass'

    def test_runner_that_registered_after_the_listing_gates_the_delete(self):
        """Review finding 4: a VM with no runner in the pass-start snapshot is re-checked before deletion."""
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'queued', age_minutes=30)]})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=30, job_id=1)])
        calls = {'n': 0}
        original = github.list_runners

        def list_runners(org_name=None, repo_name=None, token=None):
            calls['n'] += 1
            if calls['n'] == 1:
                return original(org_name=org_name, repo_name=repo_name, token=token)
            return [runner('gcp-runner-1', busy=True)]
        github.list_runners = list_runners
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == []
        assert any('registered since the listing and is busy' in r for r in reasons(report, 'kept'))

    def test_runner_that_registered_after_the_listing_is_deregistered_before_delete(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'completed')]})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=30, job_id=1)])
        calls = {'n': 0}

        def list_runners(org_name=None, repo_name=None, token=None):
            calls['n'] += 1
            return [] if calls['n'] == 1 else [runner('gcp-runner-1', runner_id=9)]
        github.list_runners = list_runners
        report, _ = run_pass(github, gcloud)
        assert github.deleted_runners == [(('org', 'example-org'), 9)]
        assert gcloud.deleted == [('gcp-runner-1', 'us-central1-b')]

    def test_relist_failure_skips_the_vm(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'completed')]})
        gcloud = FakeGCloud([vm('gcp-runner-1', age_minutes=30, job_id=1)])
        calls = {'n': 0}

        def list_runners(org_name=None, repo_name=None, token=None):
            calls['n'] += 1
            if calls['n'] == 1:
                return []
            raise RuntimeError('GitHub 502')
        github.list_runners = list_runners
        report, _ = run_pass(github, gcloud)
        assert gcloud.deleted == []
        assert any('could not re-list runners' in r for r in reasons(report, 'skipped'))

    def test_old_queued_jobs_are_retried_at_a_reduced_rate_never_dropped(self, caplog):
        """Review: giving up is a silent drop. Old jobs keep being retried, once per slow interval."""
        # 7 h queued = 420 min; 420 % 60 = 0 -> due now. 7 h 20 min -> not due. 15 min -> normal path.
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'queued', age_minutes=7 * 60),
                                                          job(2, 'queued', age_minutes=7 * 60 + 20),
                                                          job(3, 'queued', age_minutes=15)]})
        with caplog.at_level('WARNING', logger='app.services.reconcile_service'):
            report, provisioner = run_pass(github, FakeGCloud([]))
        assert sorted(c['job_id'] for c in provisioner.calls) == [1, 3]
        assert any('retried at most every 60 min' in r for r in reasons(report, 'skipped'))
        stuck = [r for r in caplog.records if 'queued for 7 h with no runner' in r.message]
        assert len(stuck) == 2, 'every stuck job is called out loudly on every pass'
        assert not any('giving up' in r.message for r in caplog.records)
        assert report['oldest_queued_job_age_seconds'] == (7 * 60 + 20) * 60

    def test_slow_retry_window_survives_a_late_pass(self):
        """Review: a pass 12 s late must not skip a whole slow interval; the window is two intervals wide."""
        # 6 h + 7 min: 367 % 60 = 7 < 2*5 -> still due (a pass at exactly 6h05 would have been 5, also due)
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'queued', age_minutes=6 * 60 + 7),
                                                          job(2, 'queued', age_minutes=6 * 60 + 12)]})
        report, provisioner = run_pass(github, FakeGCloud([]))
        assert [c['job_id'] for c in provisioner.calls] == [1]

    def test_second_consecutive_due_pass_is_blocked_by_the_vm_it_created(self):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'queued', age_minutes=6 * 60 + 5)]})
        gcloud = FakeGCloud([vm('gcp-runner-1-r', age_minutes=4, job_id=1)])
        report, provisioner = run_pass(github, gcloud)
        assert provisioner.calls == []


class TestHeartbeat:
    def test_every_completed_pass_emits_a_structured_heartbeat(self, capsys):
        github = FakeGitHub(jobs={ORG_REPO['full_name']: [job(1, 'queued', age_minutes=42)]})
        report, _ = run_pass(github, FakeGCloud([vm('gcp-runner-1', age_minutes=1, job_id=1)]))
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{')]
        beats = [entry for entry in lines if entry.get('event') == 'reconcile_heartbeat']
        assert len(beats) == 1
        beat = beats[0]
        assert beat['message'].startswith('RECONCILE_HEARTBEAT run_id=')
        assert beat['run_id'] == report['run_id']
        assert beat['queued_jobs'] == 1 and beat['live_vms'] == 1
        assert beat['oldest_queued_job_age_seconds'] == 42 * 60
        assert beat['severity'] == 'INFO' and beat['dry_run'] is False

    def test_no_queued_jobs_reports_zero_age(self, capsys):
        report, _ = run_pass(FakeGitHub(jobs={}), FakeGCloud([]))
        assert report['oldest_queued_job_age_seconds'] == 0
        beat = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{')][-1]
        assert beat['oldest_queued_job_age_seconds'] == 0

    def test_a_failed_pass_emits_no_heartbeat(self, capsys):
        class BrokenGitHub(FakeGitHub):
            def get_installation_access_token(self):
                raise RuntimeError('GitHub App auth failed')
        service = ReconcileService(github_client=BrokenGitHub(), gcloud_client=FakeGCloud(),
                                   webhook_service=FakeProvisioner(), now=NOW)
        with pytest.raises(RuntimeError):
            service.run()
        assert 'reconcile_heartbeat' not in capsys.readouterr().out
