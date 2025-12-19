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
# https://github.com/GoogleCloudPlatform/cloud-foundation-fabric/blob/v49.1.0/modules/cloud-run-v2/README.md
module "cloud_run_github_runners_manager" {
  source     = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/cloud-run-v2?ref=v50.0.0"
  project_id = module.project.project_id
  name       = "github-runners-manager-${local.region_shortnames[var.region]}"
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
      }
    }
  }
  service_config = {
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
  iam = {
    "roles/run.invoker" = ["allUsers"] # Public
  }
  deletion_protection = false
  depends_on = [
    google_secret_manager_secret_version.secret-version-default,
    time_sleep.wait_for_service_account_cloud_run
  ]
}
