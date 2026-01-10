locals {
  default_secret_manager_config = {
    global_replica_locations = {
      (var.region) = null
    }
    iam = {
      "roles/secretmanager.admin" = [
        module.service-account-cloud-run-github-runners-manager.iam_email
      ]
    }
    version_config = {
      # Secret Version TTL after destruction request.
      # This is a part of the delayed delete feature on Secret Version.
      # For secret with versionDestroyTtl>0,
      # version destruction doesn't happen immediately on calling destroy
      # instead the version goes to a disabled state and
      # the actual destruction happens after this TTL expires.
      destroy_ttl = "172800s" # 2 days
    }
  }
}

# Secret Manager for storing GitHub App credentials
# https://github.com/GoogleCloudPlatform/cloud-foundation-fabric/blob/v49.1.0/modules/secret-manager/README.md
module "secret-manager" {
  source     = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/secret-manager?ref=v51.0.0"
  project_id = module.project.project_id
  secrets = {
    github-app-id          = local.default_secret_manager_config
    github-installation-id = local.default_secret_manager_config
    github-private-key     = local.default_secret_manager_config
    github-webhook-secret  = local.default_secret_manager_config
  }
  depends_on = [
    time_sleep.wait_for_service_account_cloud_run
  ]
}

# Create initial placeholder secret versions (will be updated with actual values)
# https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/secret_manager_secret_version
resource "google_secret_manager_secret_version" "secret-version-default" {
  for_each = module.secret-manager.ids

  secret      = each.value
  secret_data = "initial secret"
  lifecycle {
    ignore_changes = all
  }
}