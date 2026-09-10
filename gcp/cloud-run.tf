# Get the container image from Artifact Registry
# https://registry.terraform.io/providers/hashicorp/google/latest/docs/data-sources/artifact_registry_docker_image
data "google_artifact_registry_docker_image" "container-image-github-runners-manager" {
  project       = module.project.project_id
  location      = var.region
  repository_id = module.artifact-registry-container.name
  image_name    = "app:latest" # Defined in cloudbuild-container.template.yaml
  depends_on = [
    null_resource.build-github-runners-manager-container
  ]
}

# Deploy the GitHub Actions Runners manager service on Cloud Run
# https://github.com/GoogleCloudPlatform/cloud-foundation-fabric/blob/v53.0.0/modules/cloud-run-v2/README.md
module "cloud_run_github_runners_manager" {
  source     = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/cloud-run-v2?ref=v53.0.0"
  project_id = module.project.project_id
  name       = local.github_runners_manager_name
  type       = "SERVICE"
  region     = var.region
  containers = {
    github-runners-manager = {
      image = data.google_artifact_registry_docker_image.container-image-github-runners-manager.self_link
      resources = {
        limits = {
          cpu    = "1000m"
          memory = "512Mi"
        }
        startup_cpu_boost = false # We do not scale to zero.
      }
      env = {
        GOOGLE_CLOUD_PROJECT = var.project_id
        GOOGLE_CLOUD_ZONE    = "${var.region}-${var.zone}"
        GITHUB_RUNNER_GROUP  = var.github_runner_group
        AUTO_TEMPLATE_PREFIX = var.github_runners_auto_template_prefix
        # Reconciler (POST /reconcile) is only accepted from this caller with this audience
        RECONCILE_INVOKER_EMAIL        = module.service-account-github-runners-reconciler.email
        RECONCILE_AUDIENCE             = local.github_runners_manager_audience
        RECONCILE_STUCK_MINUTES        = tostring(var.github_runners_reconcile_stuck_minutes)
        RECONCILE_EXCLUDE_REPOSITORIES = join(",", var.github_runners_reconcile_exclude_repositories)
        RECONCILE_SLOW_RETRY_HOURS     = tostring(var.github_runners_reconcile_slow_retry_hours)
        RECONCILE_SLOW_RETRY_MINUTES   = tostring(var.github_runners_reconcile_slow_retry_minutes)
        RECONCILE_INTERVAL_MINUTES     = tostring(local.github_runners_reconcile_interval_minutes)
        # Webhook -> Cloud Tasks -> POST /tasks/provision (only this caller, with MANAGER_URL as audience)
        PROVISION_QUEUE         = google_cloud_tasks_queue.github-runners-provision.id
        PROVISION_INVOKER_EMAIL = module.service-account-github-runners-provisioner.email
        # Stamped into runner VM metadata so the VM can report a Spot preemption to POST /runner/preempted;
        # only that route's caller (the runner VM service account) is accepted, with this URL as audience.
        MANAGER_URL                  = local.github_runners_manager_audience
        RUNNER_SERVICE_ACCOUNT_EMAIL = module.service-account-compute-vm-github-runners.email
      }
      env_from_key = {
        GITHUB_APP_ID = {
          # Secret may only be {secret} or
          # projects/{project}/secrets/{secret},
          # and secret may only have alphanumeric characters, hyphens, and underscores.
          # Secret must be a global secret not a regional secret!
          secret  = module.secret-manager.ids["github-app-id"]
          version = "latest"
        }
        GITHUB_INSTALLATION_ID = {
          secret  = module.secret-manager.ids["github-installation-id"]
          version = "latest"
        }
        GITHUB_PRIVATE_KEY = {
          secret  = module.secret-manager.ids["github-private-key"]
          version = "latest"
        }
        GITHUB_WEBHOOK_SECRET = {
          secret  = module.secret-manager.ids["github-webhook-secret"]
          version = "latest"
        }
        SETUP_USERNAME = {
          secret  = module.secret-manager.ids["setup-username"]
          version = "latest"
        }
        SETUP_PASSWORD = {
          secret  = module.secret-manager.ids["setup-password"]
          version = "latest"
        }
      }
    }
  }
  service_config = {
    # A provisioning task may wait for several Compute insert operations across zones and ladder
    # rungs (Cloud Tasks dispatch deadline 30 min); keep the request timeout at or above it.
    timeout = "${max(var.github_runners_manager_request_timeout, var.github_runners_reconcile_attempt_deadline)}s"
    # Matches gunicorn's thread count (Dockerfile): webhook requests block on the insert operation.
    max_concurrency = 32
    # Disable IAM permission check
    # There should be no requirement to pass the roles/run.invoker to the IAM block to enable public access.
    # This allows for the org policy domain restricted sharing org policy remain enabled.
    invoker_iam_disabled = true
    # Second generation Cloud Run for faster CPU.
    # The first generation with faster cold starts is still too slow for our webhook.
    gen2_execution_environment = true
    scaling = {
      min_instance_count = var.github_runners_manager_min_instance_count # Min. 1, we do not scale to zero.
      max_instance_count = var.github_runners_manager_max_instance_count
    }
  }
  service_account_config = {
    create = false
    email  = module.service-account-cloud-run-github-runners-manager.email
  }
  deletion_protection = false
  depends_on = [
    google_secret_manager_secret_version.secret-version-default,
    google_secret_manager_secret_version.secret-version-setup,
    time_sleep.wait_for_service_account_cloud_run,
    time_sleep.wait_for_service_account_reconciler,
    time_sleep.wait_for_service_account_provisioner
  ]
}
