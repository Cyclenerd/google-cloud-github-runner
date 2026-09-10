"""
Google Cloud Client for managing GCE instances.
"""
import concurrent.futures
import datetime
import logging
import os
import re
import uuid
import shlex
import time
import google.cloud.compute_v1 as compute_v1
from google.api_core import exceptions as gapi_exceptions

logger = logging.getLogger(__name__)

# How long to wait for an instances.insert operation before giving up (seconds).
DEFAULT_INSERT_TIMEOUT_SECONDS = 120
# How long the list of zones in the region is cached (seconds).
ZONE_CACHE_SECONDS = 600
# Instance label that records the zone the VM landed in after zone fallback.
ZONE_LABEL = 'gha-zone'
# Instance label that records the GitHub workflow job id the VM was created for.
JOB_ID_LABEL = 'gha-job-id'
# Instance name prefix shared by every runner VM the manager creates.
INSTANCE_NAME_PREFIX = 'gcp-runner-'
# Instance states that count as "alive" for the reconciler.
LIVE_INSTANCE_STATUSES = ('PROVISIONING', 'STAGING', 'RUNNING', 'REPAIRING')

# Operation error codes that mean "this zone cannot serve the request right now".
# https://cloud.google.com/compute/docs/troubleshooting/troubleshooting-vm-creation
RETRY_ELSEWHERE_CODE_PREFIXES = (
    'ZONE_RESOURCE_POOL_EXHAUSTED',
    'QUOTA_EXCEEDED',
)
# Message fragments that indicate a stockout even when the code is generic.
RETRY_ELSEWHERE_MESSAGE_MARKERS = (
    'stockout',
    'does not have enough resources',
    'currently unavailable',
)


class InstanceCreationError(Exception):
    """The instances.insert operation did not succeed. Never swallowed."""


class ZoneCapacityError(InstanceCreationError):
    """The insert failed for a capacity reason (stockout/quota); another zone may work."""

    def __init__(self, message, code=None, zone=None):
        super().__init__(message)
        self.code = code
        self.zone = zone
        self.attempts = [self]  # one entry per zone tried, set by _insert_across_zones


def label_value(value):
    """Make a string a valid GCE label value: lowercase, [a-z0-9_-], at most 63 characters."""
    return re.sub(r'[^a-z0-9_-]', '-', str(value or '').lower())[:63]


def classify_operation_errors(errors):
    """
    Classify the ``error.errors`` list of a finished Compute operation.

    Args:
        errors: iterable of compute_v1.Errors (or anything with .code/.message/.error_details).

    Returns:
        tuple(bool, str): (retry_elsewhere, human readable summary "CODE: message; ...").
    """
    retry_elsewhere = False
    parts = []
    for error in errors or []:
        code = str(getattr(error, 'code', '') or '')
        message = str(getattr(error, 'message', '') or '')
        reason = ''
        zone = ''
        for detail in getattr(error, 'error_details', None) or []:
            error_info = getattr(detail, 'error_info', None)
            if error_info is not None:
                reason = reason or str(getattr(error_info, 'reason', '') or '')
                metadatas = getattr(error_info, 'metadatas', None) or {}
                zone = zone or str(metadatas.get('zone', '') if hasattr(metadatas, 'get') else '')
        summary = f"{code}: {message}"
        if reason:
            summary += f" (reason={reason}"
            summary += f", zone={zone})" if zone else ")"
        parts.append(summary)
        haystack = f"{message} {reason}".lower()
        if code.startswith(RETRY_ELSEWHERE_CODE_PREFIXES) or reason.lower() == 'stockout' \
                or any(marker in haystack for marker in RETRY_ELSEWHERE_MESSAGE_MARKERS):
            retry_elsewhere = True
    return retry_elsewhere, '; '.join(parts)


class GCloudClient:
    """Client for interacting with Google Cloud Compute Engine API."""

    def __init__(self):
        """Initialize GCloudClient with project and zone configuration."""
        self.project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')
        self.zone = os.environ.get('GOOGLE_CLOUD_ZONE', 'us-central1-a')
        self.github_runner_group = os.environ.get('GITHUB_RUNNER_GROUP', '').strip()
        self.region = '-'.join(self.zone.split('-')[:-1])
        self.insert_timeout = int(os.environ.get('GCE_INSERT_TIMEOUT_SECONDS', DEFAULT_INSERT_TIMEOUT_SECONDS))

        if not self.project_id:
            logger.warning("GOOGLE_CLOUD_PROJECT not set. GCloudClient will not work correctly.")

        # https://docs.cloud.google.com/python/docs/reference/compute/latest/google.cloud.compute_v1.services.instances.InstancesClient
        self.instance_client = compute_v1.InstancesClient()
        # Create a RegionInstanceTemplatesClient for retrieving templates in a specific region
        # https://docs.cloud.google.com/python/docs/reference/compute/latest/google.cloud.compute_v1.services.region_instance_templates
        self.instance_templates_client = compute_v1.RegionInstanceTemplatesClient()
        # Zones of the region are listed lazily and cached for ZONE_CACHE_SECONDS.
        self._zones_client = None
        self._zones_cache = None
        self._zones_cache_time = 0.0

    def candidate_zones(self):
        """
        Zones of the template region to try, in a stable order.

        The configured zone (GOOGLE_CLOUD_ZONE) comes first, followed by the other UP zones of
        the same region sorted by name. The list comes from the Compute API, not a hardcoded table.
        On any listing error only the configured zone is returned (and the error is logged).

        Returns:
            list[str]: zone names, e.g. ['us-central1-b', 'us-central1-a', 'us-central1-c'].
        """
        now = time.monotonic()
        if self._zones_cache is not None and now - self._zones_cache_time < ZONE_CACHE_SECONDS:
            return list(self._zones_cache)
        zones = [self.zone]
        try:
            if self._zones_client is None:
                # https://docs.cloud.google.com/python/docs/reference/compute/latest/google.cloud.compute_v1.services.zones
                self._zones_client = compute_v1.ZonesClient()
            others = []
            for zone in self._zones_client.list(project=self.project_id):
                region = str(getattr(zone, 'region', '') or '').rstrip('/').split('/')[-1]
                status = str(getattr(zone, 'status', '') or '')
                if region != self.region or status.upper() != 'UP' or zone.name == self.zone:
                    continue
                others.append(zone.name)
            zones.extend(sorted(others))
            self._zones_cache = list(zones)
            self._zones_cache_time = now
        except Exception as e:
            logger.warning(
                "Could not list zones of region %s (%s); using configured zone %s only",
                self.region,
                e,
                self.zone,
            )
        return zones

    def list_templates(self):
        """All regional instance templates of the project's region (empty list on error, logged)."""
        try:
            return list(self.instance_templates_client.list(project=self.project_id, region=self.region))
        except Exception as e:
            logger.error("Could not list instance templates in region %s: %s", self.region, e)
            return []

    def _get_template_name(self, template_name, templates=None):
        """
        Find a matching instance template by name prefix.

        Args:
            template_name (str): The name prefix to search for.
            templates (list): Preloaded result of list_templates() to avoid one API call per lookup.

        Returns:
            google.cloud.compute_v1.InstanceTemplate or None: The matching template resource.
        """
        # Replace dots with dashes for template name, so gcp-ubuntu-24.04 matches gcp-ubuntu-24-04
        prefix = template_name.replace('.', '-')
        # logger.info(f"Prefix: {prefix}")
        # Create regex pattern: prefix followed by dash, at least 12 digits, and optional alphanumeric characters
        pattern = re.compile(f"^{re.escape(prefix)}-\\d{{14,}}[a-z0-9]*$")
        if templates is None:
            templates = self.list_templates()
        for template in templates:
            # logger.info(f"Template: {template.name}")
            if pattern.match(template.name):
                return template
        return None

    def has_template_for(self, label, templates=None):
        """True when a job label has a matching instance template (resolved against ``templates`` if given)."""
        if templates is None:
            templates = self.list_templates()
        return self._get_template_name(label, templates=templates) is not None

    def create_runner_instance(
        self,
        registration_token,
        repo_url,
        template_name,
        instance_label=None,
        delivery_id=None,
        job_id=None,
        name_suffix='',
    ):
        """
        Create a new GCE instance for a GitHub Actions runner.

        Args:
            registration_token (str): The GitHub Actions runner registration token.
            repo_url (str): The URL of the repository or organization.
            template_name (str): The name of the instance template to use.
            instance_label (str): Label to add to the Instance for Cost Tracking.
            delivery_id (str): The GitHub webhook delivery ID for log correlation.
            job_id (int|str): GitHub workflow job id. When given, the instance is named after it
                (``gcp-runner-<job_id>``) so two creators racing for the same job in the same zone
                collide on the name instead of both provisioning, and it is stored in the
                ``gha-job-id`` label for the reconciler.
            name_suffix (str): Optional suffix appended to a job-derived name (e.g. ``-r``).

        Returns:
            str or None: The name of the created instance, or None when no template matches.

        Raises:
            ZoneCapacityError: no zone of the region had capacity.
            InstanceCreationError: any other creation failure.
        """
        template = self._get_template_name(template_name)
        if template is None:
            logger.warning(
                "No matching instance template found for label '%s' in region %s. "
                "Skipping instance creation. delivery_id: %s",
                template_name,
                self.region,
                delivery_id,
            )
            return None
        logger.info(
            "Found matching instance template: %s, delivery_id: %s",
            template.name,
            delivery_id,
        )

        # Name must start with a lowercase letter followed by up to 62 lowercase letters,
        # numbers, or hyphens, and cannot end with a hyphen.
        if job_id is not None:
            instance_id = f"{job_id}{name_suffix}"
        else:
            instance_id = uuid.uuid4().hex[:16]
        if template.name.startswith("dependabot"):
            instance_name = f"{INSTANCE_NAME_PREFIX}dependabot-{instance_id}"
        else:
            instance_name = f"{INSTANCE_NAME_PREFIX}{instance_id}"

        labels = {}
        if instance_label is not None:
            owner, repo = instance_label.split("/")
            labels = {
                "gha-owner": label_value(owner),
                "gha-repo": label_value(repo),
                "gha-runner": label_value(template_name),
            }
        if job_id is not None:
            labels[JOB_ID_LABEL] = str(job_id)

        logger.info(
            "Creating GCE instance %s with template %s, delivery_id: %s",
            instance_name,
            template.self_link,
            delivery_id,
        )

        def metadata_for(zone):
            return self._build_metadata(registration_token, repo_url, template_name, instance_name, job_id)

        try:
            self._insert_across_zones(instance_name, template, labels, metadata_for, delivery_id)
        except ZoneCapacityError as e:
            # Every zone of the region ran out of capacity; _insert_across_zones logged each attempt.
            tried = ', '.join(f"{a.zone} ({a.code})" for a in e.attempts)
            logger.error(
                "No zone in region %s could create instance %s; tried %s, delivery_id: %s",
                self.region,
                instance_name,
                tried,
                delivery_id,
            )
            raise
        return instance_name

    def _build_metadata(self, registration_token, repo_url, template_name, instance_name, job_id):
        """Instance metadata: the startup script that registers the runner."""
        # Use shlex.quote to prevent command injection
        runner_group_flag = ""
        if self.github_runner_group:
            runner_group_flag = f" --runnergroup {shlex.quote(self.github_runner_group)}"

        startup_script = (
            "cd /actions-runner && "
            f"sudo -u runner ./config.sh --url {shlex.quote(repo_url)} "
            f"--token {shlex.quote(registration_token)} "
            f"--name {shlex.quote(instance_name)} "
            f"--labels {shlex.quote(template_name)} "
            f"{runner_group_flag} "
            "--ephemeral "
            "--unattended "
            "--replace "
            "--no-default-labels "
            "--disableupdate && "
            "sudo -u runner ./run.sh"
        )
        metadata = compute_v1.Metadata()
        metadata.items = [
            compute_v1.Items(key="startup-script", value=startup_script),
            compute_v1.Items(key="vmDnsSetting", value="ZonalOnly"),
            compute_v1.Items(key="block-project-ssh-keys", value="true"),
        ]
        return metadata

    def _insert_across_zones(self, instance_name, template, labels, metadata_for, delivery_id=None):
        """
        Insert ``instance_name`` from ``template`` in the first zone of the region with capacity.

        Tries the configured zone first, then the other UP zones of the region (templates are
        regional). Only capacity errors move on to the next zone; anything else raises at once.

        Returns:
            str: the zone the instance was created in (or already existed in).

        Raises:
            ZoneCapacityError: every zone failed for capacity reasons; ``.attempts`` lists them.
        """
        capacity_failures = []
        for zone in self.candidate_zones():
            instance_resource = compute_v1.Instance()  # google.cloud.compute_v1.types.Instance
            instance_resource.name = instance_name
            instance_resource.labels = {**labels, ZONE_LABEL: zone}
            instance_resource.metadata = metadata_for(zone)
            # https://docs.cloud.google.com/python/docs/reference/compute/latest/google.cloud.compute_v1.types.InsertInstanceRequest
            request = compute_v1.InsertInstanceRequest(
                project=self.project_id,
                zone=zone,
                instance_resource=instance_resource,
                source_instance_template=template.self_link
            )
            try:
                # https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/insert
                operation = self.instance_client.insert(request=request)
                logger.info(
                    "Instance creation operation started: %s, zone: %s, delivery_id: %s",
                    operation.name,
                    zone,
                    delivery_id,
                )
            except gapi_exceptions.Conflict as e:
                # Another creator (webhook or reconciler) already inserted this name in this zone.
                logger.info(
                    "Instance %s already exists in zone %s; another creator won (%s), delivery_id: %s",
                    instance_name,
                    zone,
                    e,
                    delivery_id,
                )
                return zone
            except Exception as e:
                logger.error(
                    "Failed to create instance %s in zone %s: %s, delivery_id: %s",
                    instance_name,
                    zone,
                    e,
                    delivery_id,
                )
                raise

            # Wait for the operation: capacity errors (stockout, quota) are operation-level
            # errors, so returning here would report success for a VM that never existed.
            try:
                self._wait_for_insert(operation, instance_name, zone, delivery_id=delivery_id)
            except ZoneCapacityError as e:
                capacity_failures.append(e)
                continue
            logger.info(
                "Instance %s created in zone %s with template %s, delivery_id: %s",
                instance_name,
                zone,
                template.name,
                delivery_id,
            )
            return zone

        tried = ', '.join(f"{e.zone} ({e.code})" for e in capacity_failures)
        last = capacity_failures[-1]
        error = ZoneCapacityError(
            f"No zone in region {self.region} could create {instance_name}; tried {tried}",
            code=last.code,
            zone=last.zone,
        )
        error.attempts = capacity_failures
        raise error from last

    def _wait_for_insert(self, operation, instance_name, zone, delivery_id=None):
        """
        Block until the insert operation finishes and raise if it did not succeed.

        Raises:
            ZoneCapacityError: the zone is out of capacity/quota; another zone may work.
            InstanceCreationError: any other failure, including a timed-out wait.
        """
        try:
            operation.result(timeout=self.insert_timeout)
        except concurrent.futures.TimeoutError:
            # The operation may still complete; do NOT retry elsewhere or we could double-provision.
            message = (
                f"Instance creation for {instance_name} in zone {zone} timed out after "
                f"{self.insert_timeout}s (operation {getattr(operation, 'name', '?')}); not retrying"
            )
            logger.error("%s, delivery_id: %s", message, delivery_id)
            raise InstanceCreationError(message)
        except gapi_exceptions.GoogleAPICallError as e:
            errors = self._operation_errors(operation)
            retry_elsewhere, summary = classify_operation_errors(errors)
            if not summary:
                summary = str(e)
            code = str(getattr(errors[0], 'code', '') or '') if errors else ''
            if retry_elsewhere:
                logger.warning(
                    "Instance creation for %s in zone %s failed with a capacity error: %s, delivery_id: %s",
                    instance_name,
                    zone,
                    summary,
                    delivery_id,
                )
                raise ZoneCapacityError(
                    f"Zone {zone} has no capacity for {instance_name}: {summary}", code=code, zone=zone
                ) from e
            logger.error(
                "Instance creation for %s in zone %s failed: %s, delivery_id: %s",
                instance_name,
                zone,
                summary,
                delivery_id,
            )
            raise InstanceCreationError(
                f"Instance creation for {instance_name} in zone {zone} failed: {summary}"
            ) from e

        # Defensive: a DONE operation that carries errors but did not raise is still a failure.
        errors = self._operation_errors(operation)
        if errors:
            retry_elsewhere, summary = classify_operation_errors(errors)
            code = str(getattr(errors[0], 'code', '') or '')
            logger.error(
                "Instance creation for %s in zone %s finished with errors: %s, delivery_id: %s",
                instance_name,
                zone,
                summary,
                delivery_id,
            )
            if retry_elsewhere:
                raise ZoneCapacityError(
                    f"Zone {zone} has no capacity for {instance_name}: {summary}", code=code, zone=zone
                )
            raise InstanceCreationError(
                f"Instance creation for {instance_name} in zone {zone} finished with errors: {summary}"
            )

    @staticmethod
    def _operation_errors(operation):
        """Return the list of compute_v1.Errors attached to an operation (empty if none)."""
        try:
            error = getattr(operation, 'error', None)
            errors = list(getattr(error, 'errors', None) or [])
        except Exception:
            return []
        # Guard against MagicMock-like objects in tests returning non-Errors items.
        return [e for e in errors if isinstance(getattr(e, 'code', None), str)]

    def list_runner_instances(self, name_prefix=INSTANCE_NAME_PREFIX):
        """
        Every runner VM the manager created, in any zone of the project.

        Args:
            name_prefix (str): only instances whose name starts with this are returned.

        Returns:
            list[dict]: name, zone, status, labels (dict), created_at (aware datetime or None).
        """
        # https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/aggregatedList
        # Filtered client-side on the name prefix: the project holds few VMs and a server-side
        # filter that silently matched nothing would hide every runner from the reconciler.
        request = compute_v1.AggregatedListInstancesRequest(project=self.project_id)
        instances = []
        for zone_key, scoped_list in self.instance_client.aggregated_list(request=request):
            for instance in getattr(scoped_list, 'instances', None) or []:
                if not str(instance.name).startswith(name_prefix):
                    continue
                zone = str(getattr(instance, 'zone', '') or '').rstrip('/').split('/')[-1] or str(zone_key).split('/')[-1]
                created_at = None
                raw = getattr(instance, 'creation_timestamp', None)
                if raw:
                    try:
                        created_at = datetime.datetime.fromisoformat(str(raw))
                    except ValueError:
                        created_at = None
                instances.append({
                    'name': instance.name,
                    'zone': zone,
                    'status': str(getattr(instance, 'status', '') or ''),
                    'labels': dict(getattr(instance, 'labels', None) or {}),
                    'created_at': created_at,
                })
        return instances

    def find_instance_zone(self, instance_name, delivery_id=None):
        """
        Locate the zone an instance lives in, searching every zone of the project.

        Returns:
            str or None: the zone name, or None when no instance with that name exists.

        Raises:
            Exception: if the aggregated list call itself fails.
        """
        # Same unfiltered aggregatedList as list_runner_instances, matched client-side: a server-side
        # filter that silently matched nothing would turn every delete into a no-op.
        for instance in self.list_runner_instances(name_prefix=instance_name):
            if instance['name'] == instance_name:
                return instance['zone']
        return None

    def delete_runner_instance(self, instance_name, delivery_id=None, zone=None):
        """
        Delete a GCE instance, wherever in the project it lives.

        Args:
            instance_name (str): The name of the instance to delete.
            delivery_id (str): The GitHub webhook delivery ID for log correlation.
            zone (str): Zone of the instance if already known; otherwise it is looked up.

        Returns:
            str or None: the zone the delete was issued in, or None if the instance was not found.
        """
        if zone is None:
            try:
                zone = self.find_instance_zone(instance_name, delivery_id=delivery_id)
            except Exception as e:
                logger.warning(
                    "Could not look up zone of instance %s (%s); trying configured zone %s, delivery_id: %s",
                    instance_name,
                    e,
                    self.zone,
                    delivery_id,
                )
                zone = self.zone
            if zone is None:
                logger.warning(
                    "Instance %s not found in any zone of project %s; nothing to delete, delivery_id: %s",
                    instance_name,
                    self.project_id,
                    delivery_id,
                )
                return None

        logger.info(
            "Deleting GCE instance %s in zone %s, delivery_id: %s", instance_name, zone, delivery_id
        )
        try:
            operation = self.instance_client.delete(
                project=self.project_id,
                zone=zone,
                instance=instance_name
            )
            logger.info(
                "Instance deletion operation started: %s, zone: %s, delivery_id: %s",
                operation.name,
                zone,
                delivery_id,
            )
            return zone
        except Exception as e:
            logger.error(
                "Failed to delete instance %s in zone %s: %s, delivery_id: %s",
                instance_name,
                zone,
                e,
                delivery_id,
            )
            raise
