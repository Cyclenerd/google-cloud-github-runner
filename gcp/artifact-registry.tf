# Artifact Registry for storing the GitHub Actions Runners manager container image
# https://github.com/GoogleCloudPlatform/cloud-foundation-fabric/blob/v49.1.0/modules/artifact-registry/README.md
module "artifact-registry-container" {
  source                 = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/artifact-registry?ref=v50.0.0"
  project_id             = module.project.project_id
  location               = var.region
  name                   = "container-github-runners-manager"
  description            = "Registry for GitHub Actions Runners manager (Terraform-managed)"
  format                 = { docker = { standard = {} } }
  cleanup_policy_dry_run = false
  cleanup_policies = {
    keep-3-versions = {
      action = "KEEP"
      most_recent_versions = {
        keep_count = 3
      }
    }
    delete = {
      action = "DELETE"
      condition = {
        tag_state = "UNTAGGED"
      }
    }
  }
  iam = {
    "roles/artifactregistry.writer" = [
      module.service-account-cloud-build-github-runners.iam_email
    ]
  }
  depends_on = [
    time_sleep.wait_for_service_account_cloud_build
  ]
}
