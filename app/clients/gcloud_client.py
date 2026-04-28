"""
Google Cloud Client for managing GCE instances.
"""
import logging
import os
import re
import uuid
import shlex
import google.cloud.compute_v1 as compute_v1

logger = logging.getLogger(__name__)


class GCloudClient:
    """Client for interacting with Google Cloud Compute Engine API."""

    def __init__(self):
        """Initialize GCloudClient with project and zone configuration."""
        self.project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')
        self.zone = os.environ.get('GOOGLE_CLOUD_ZONE', 'us-central1-a')
        self.region = '-'.join(self.zone.split('-')[:-1])

        if not self.project_id:
            logger.warning("GOOGLE_CLOUD_PROJECT not set. GCloudClient will not work correctly.")

        # https://docs.cloud.google.com/python/docs/reference/compute/latest/google.cloud.compute_v1.services.instances.InstancesClient
        self.instance_client = compute_v1.InstancesClient()
        # Create a RegionInstanceTemplatesClient for retrieving templates in a specific region
        # https://docs.cloud.google.com/python/docs/reference/compute/latest/google.cloud.compute_v1.services.region_instance_templates
        self.instance_templates_client = compute_v1.RegionInstanceTemplatesClient()

    def _get_template_name(self, template_name):
        """
        Find a matching instance template by name prefix.

        Args:
            template_name (str): The name prefix to search for.

        Returns:
            google.cloud.compute_v1.InstanceTemplate or None: The matching template resource.
        """
        # Replace dots with dashes for template name, so gcp-ubuntu-24.04 matches gcp-ubuntu-24-04
        prefix = template_name.replace('.', '-')
        # logger.info(f"Prefix: {prefix}")
        # Create regex pattern: prefix followed by dash, at least 12 digits, and optional alphanumeric characters
        pattern = re.compile(f"^{re.escape(prefix)}-\\d{{14,}}[a-z0-9]*$")
        try:
            # List all templates to find one that matches the pattern
            for template in self.instance_templates_client.list(project=self.project_id, region=self.region):
                # logger.info(f"Template: {template.name}")
                if pattern.match(template.name):
                    return template
            return None
        except Exception:
            return None

    def create_runner_instance(
        self,
        registration_token,
        repo_url,
        template_name,
        instance_label=None,
        delivery_id=None,
    ):
        """
        Create a new GCE instance for a GitHub Actions runner.

        Args:
            registration_token (str): The GitHub Actions runner registration token.
            repo_url (str): The URL of the repository or organization.
            template_name (str): The name of the instance template to use.
            instance_label (str): Label to add to the Instance for Cost Tracking.
            delivery_id (str): The GitHub webhook delivery ID for log correlation.

        Returns:
            str: The name of the created instance.
        """
        instance_template_resource = self._get_template_name(template_name)
        if instance_template_resource:
            logger.info(
                "Found matching instance template: %s, delivery_id: %s",
                instance_template_resource.name,
                delivery_id,
            )
        else:
            logger.warning(
                "No matching instance template found for label '%s' in region %s. "
                "Skipping instance creation. delivery_id: %s",
                template_name,
                self.region,
                delivery_id,
            )
            return None

        instance_uuid = uuid.uuid4().hex[:16]
        if instance_template_resource.name.startswith("dependabot"):
            instance_name = f"dependabot-{instance_uuid}"
        else:
            instance_name = f"runner-{instance_uuid}"

        logger.info(
            "Creating GCE instance %s with template %s, delivery_id: %s",
            instance_name,
            instance_template_resource.self_link,
            delivery_id,
        )

        # Set instance name
        instance_resource = compute_v1.Instance()  # google.cloud.compute_v1.types.Instance
        instance_resource.name = instance_name

        if instance_label is not None:
            owner, repo = instance_label.split("/")
            instance_resource.labels = {
                "gha-owner": owner.lower(),
                "gha-repo": repo.lower(),
                "gha-runner": template_name
            }

        # Set metadata (startup script) - use shlex.quote to prevent command injection
        startup_script = (
            f"sudo -u runner /actions-runner/config.sh --url {shlex.quote(repo_url)} "
            f"--token {shlex.quote(registration_token)} "
            f"--name {shlex.quote(instance_name)} --labels {shlex.quote(template_name)} "
            "--ephemeral --unattended --no-default-labels --disableupdate && "
            "sudo -u runner /actions-runner/run.sh"
        )
        metadata = compute_v1.Metadata()
        metadata.items = [
            compute_v1.Items(key="startup-script", value=startup_script),
            compute_v1.Items(key="vmDnsSetting", value="ZonalOnly"),
            compute_v1.Items(key="block-project-ssh-keys", value="true"),
        ]
        instance_resource.metadata = metadata

        # Create the request
        # https://docs.cloud.google.com/python/docs/reference/compute/latest/google.cloud.compute_v1.types.InsertInstanceRequest
        request = compute_v1.InsertInstanceRequest(
            project=self.project_id,
            zone=self.zone,
            instance_resource=instance_resource,
            source_instance_template=instance_template_resource.self_link
        )

        try:
            # https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/insert
            operation = self.instance_client.insert(request=request)
            logger.info(
                "Instance creation operation started: %s, delivery_id: %s",
                operation.name,
                delivery_id,
            )
            return instance_name
        except Exception as e:
            logger.error(
                "Failed to create instance: %s, delivery_id: %s", e, delivery_id
            )
            raise

    def delete_runner_instance(self, instance_name, delivery_id=None):
        """
        Delete a GCE instance.

        Args:
            instance_name (str): The name of the instance to delete.
            delivery_id (str): The GitHub webhook delivery ID for log correlation.
        """
        logger.info(
            "Deleting GCE instance %s, delivery_id: %s", instance_name, delivery_id
        )
        try:
            operation = self.instance_client.delete(
                project=self.project_id,
                zone=self.zone,
                instance=instance_name
            )
            logger.info(
                "Instance deletion operation started: %s, delivery_id: %s",
                operation.name,
                delivery_id,
            )
        except Exception as e:
            logger.error(
                "Failed to delete instance %s: %s, delivery_id: %s",
                instance_name,
                e,
                delivery_id,
            )
            raise
