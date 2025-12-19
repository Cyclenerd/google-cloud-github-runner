"""
Service for managing application configuration and secrets.
"""
import os
import logging
from google.cloud import secretmanager

logger = logging.getLogger(__name__)


class ConfigService:
    """Service to handle reading and writing configuration from .env or Google Secret Manager."""

    def __init__(self):
        """Initialize ConfigService and detect execution environment (Cloud Run or local)."""
        self.project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')
        self.region = os.environ.get('GCP_REGION', 'us-central1')
        self.service_name = os.environ.get('K_SERVICE', None)

        self.is_cloud_run = self.service_name is not None

        if self.is_cloud_run:
            if not self.project_id:
                logger.warning("GOOGLE_CLOUD_PROJECT not set. ConfigService will not work correctly.")
            try:
                self.secret_client = secretmanager.SecretManagerServiceClient()
            except Exception as e:
                logger.error(f"Failed to initialize GCP clients: {e}")
                self.is_cloud_run = False
        else:
            logger.info("Running in local mode (K_SERVICE not set)")
            self.secret_client = None

    def store_github_app_id(self, app_id):
        """Store GITHUB_APP_ID in Secret Manager or local .env."""
        try:
            if self.is_cloud_run and self.project_id:
                self._store_app_id_cloud(app_id)
            else:
                logger.info("Running in local mode. Saving GITHUB_APP_ID locally.")
                self._store_app_id_local(app_id)
            return True
        except Exception as e:
            logger.error(f"Failed to store GITHUB_APP_ID: {e}")
            raise

    def store_github_installation_id(self, installation_id):
        """Store GITHUB_INSTALLATION_ID in Secret Manager or local .env."""
        try:
            if self.is_cloud_run and self.project_id:
                self._store_installation_id_cloud(installation_id)
            else:
                logger.info("Running in local mode. Saving GITHUB_INSTALLATION_ID locally.")
                self._store_installation_id_local(installation_id)
            return True
        except Exception as e:
            logger.error(f"Failed to store GITHUB_INSTALLATION_ID: {e}")
            raise

    def store_github_private_key(self, private_key):
        """Store GITHUB_PRIVATE_KEY in Secret Manager or local .env."""
        try:
            if self.is_cloud_run and self.project_id:
                self._store_private_key_cloud(private_key)
            else:
                logger.info("Running in local mode. Saving GITHUB_PRIVATE_KEY locally.")
                self._store_private_key_local(private_key)
            return True
        except Exception as e:
            logger.error(f"Failed to store GITHUB_PRIVATE_KEY: {e}")
            raise

    def store_github_webhook_secret(self, webhook_secret):
        """Store GITHUB_WEBHOOK_SECRET in Secret Manager or local .env."""
        try:
            if self.is_cloud_run and self.project_id:
                self._store_webhook_secret_cloud(webhook_secret)
            else:
                logger.info("Running in local mode. Saving GITHUB_WEBHOOK_SECRET locally.")
                self._store_webhook_secret_local(webhook_secret)
            return True
        except Exception as e:
            logger.error(f"Failed to store GITHUB_WEBHOOK_SECRET: {e}")
            raise

    def _store_app_id_cloud(self, app_id):
        """Store GITHUB_APP_ID in GCP Secret Manager."""
        try:
            parent = f"projects/{self.project_id}"
            self.secret_client.add_secret_version(
                request={
                    "parent": f"{parent}/secrets/github-app-id",
                    "payload": {"data": str(app_id).encode("UTF-8")}
                }
            )
            logger.info("Added new version to secret: github-app-id")
        except Exception as e:
            logger.error(f"Failed to write GITHUB_APP_ID secret: {e}")
            raise

    def _store_installation_id_cloud(self, installation_id):
        """Store GITHUB_INSTALLATION_ID in GCP Secret Manager."""
        try:
            parent = f"projects/{self.project_id}"
            self.secret_client.add_secret_version(
                request={
                    "parent": f"{parent}/secrets/github-installation-id",
                    "payload": {"data": str(installation_id).encode("UTF-8")}
                }
            )
            logger.info("Added new version to secret: github-installation-id")
        except Exception as e:
            logger.error(f"Failed to write GITHUB_INSTALLATION_ID secret: {e}")
            raise

    def _store_private_key_cloud(self, private_key):
        """Store GITHUB_PRIVATE_KEY in GCP Secret Manager."""
        try:
            parent = f"projects/{self.project_id}"
            self.secret_client.add_secret_version(
                request={
                    "parent": f"{parent}/secrets/github-private-key",
                    "payload": {"data": str(private_key).encode("UTF-8")}
                }
            )
            logger.info("Added new version to secret: github-private-key")
        except Exception as e:
            logger.error(f"Failed to write GITHUB_PRIVATE_KEY secret: {e}")
            raise

    def _store_webhook_secret_cloud(self, webhook_secret):
        """Store GITHUB_WEBHOOK_SECRET in GCP Secret Manager."""
        try:
            parent = f"projects/{self.project_id}"
            self.secret_client.add_secret_version(
                request={
                    "parent": f"{parent}/secrets/github-webhook-secret",
                    "payload": {"data": str(webhook_secret).encode("UTF-8")}
                }
            )
            logger.info("Added new version to secret: github-webhook-secret")
        except Exception as e:
            logger.error(f"Failed to write GITHUB_WEBHOOK_SECRET secret: {e}")
            raise

    def _store_app_id_local(self, app_id):
        """Store GITHUB_APP_ID in local .env file."""
        try:
            self._update_env_file("GITHUB_APP_ID", str(app_id))
            logger.info("GITHUB_APP_ID saved to .env")
        except Exception as e:
            logger.error(f"Failed to write GITHUB_APP_ID to .env: {e}")
            raise

    def _store_installation_id_local(self, installation_id):
        """Store GITHUB_INSTALLATION_ID in local .env file."""
        try:
            self._update_env_file("GITHUB_INSTALLATION_ID", str(installation_id))
            logger.info("GITHUB_INSTALLATION_ID saved to .env")
        except Exception as e:
            logger.error(f"Failed to write GITHUB_INSTALLATION_ID to .env: {e}")
            raise

    def _store_private_key_local(self, private_key):
        """Store GITHUB_PRIVATE_KEY in local file and reference in .env."""
        try:
            key_filename = "github-private-key.pem"
            # Create file with secure permissions (600 = rw-------)
            with os.fdopen(os.open(key_filename, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
                f.write(private_key)
            logger.info(f"Saved private key to {key_filename}")

            self._update_env_file("GITHUB_PRIVATE_KEY_PATH", key_filename)
            logger.info("GITHUB_PRIVATE_KEY_PATH saved to .env")
        except Exception as e:
            logger.error(f"Failed to write GITHUB_PRIVATE_KEY_PATH locally: {e}")
            raise

    def _store_webhook_secret_local(self, webhook_secret):
        """Store GITHUB_WEBHOOK_SECRET in local .env file."""
        try:
            self._update_env_file("GITHUB_WEBHOOK_SECRET", str(webhook_secret))
            logger.info("GITHUB_WEBHOOK_SECRET saved to .env")
        except Exception as e:
            logger.error(f"Failed to write GITHUB_WEBHOOK_SECRET to .env: {e}")
            raise

    def _update_env_file(self, key, value):
        """Update or append a key-value pair in the .env file."""
        env_path = ".env"
        env_lines = []
        key_found = False

        # Read existing .env file if it exists
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                env_lines = f.readlines()

            # Update existing key if found
            for i, line in enumerate(env_lines):
                if line.strip().startswith(f"{key}="):
                    env_lines[i] = f"{key}={value}\n"
                    key_found = True
                    break

        # Append key if not found
        if not key_found:
            if env_lines and not env_lines[-1].endswith("\n"):
                env_lines.append("\n")
            env_lines.append(f"{key}={value}\n")

        # Write back to .env file
        with open(env_path, "w") as f:
            f.writelines(env_lines)

    def is_configured(self):
        """Check if the GitHub App is already configured."""
        try:
            app_id = os.environ.get('GITHUB_APP_ID')
            installation_id = os.environ.get('GITHUB_INSTALLATION_ID')

            if self.is_cloud_run:
                private_key_secret = os.environ.get('GITHUB_PRIVATE_KEY')
                has_key = (private_key_secret is not None
                           and 'initial' not in private_key_secret.lower())
            else:
                private_key_path = os.environ.get('GITHUB_PRIVATE_KEY_PATH')
                has_key = (private_key_path
                           and os.path.exists(private_key_path)
                           and 'initial' not in private_key_path.lower())

            app_id_valid = app_id is not None and 'initial' not in app_id.lower()
            installation_id_valid = installation_id is not None and 'initial' not in installation_id.lower()

            is_complete = (app_id_valid and installation_id_valid and has_key)

            return {
                'is_configured': is_complete,
                'app_id': app_id,
                'installation_id': installation_id,
                'has_private_key': has_key,
            }

        except Exception as e:
            logger.error(f"Error checking configuration: {e}")
            return {
                'is_configured': False,
                'app_id': None,
                'installation_id': None,
                'has_private_key': False,
            }
