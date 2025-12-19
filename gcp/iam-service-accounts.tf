# https://github.com/GoogleCloudPlatform/cloud-foundation-fabric/blob/v49.1.0/modules/iam-service-account/README.md

# Service Account for GitHub Actions Runners (Compute Engine VMs)
module "service-account-compute-vm-github-runners" {
  source       = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/iam-service-account?ref=v49.1.0"
  project_id   = module.project.project_id
  name         = "github-runners"
  display_name = "Compute VM - GitHub Actions Runners (Terraform managed)"
  iam = {
    "roles/iam.serviceAccountUser" = [
      module.service-account-cloud-run-github-runners-manager.iam_email
    ]
  }
  iam_project_roles = {
    (module.project.project_id) = [
      "roles/logging.logWriter",
      "roles/monitoring.metricWriter",
    ]
  }
}

# Wait for service account to be fully propagated in Google Cloud IAM
resource "time_sleep" "wait_for_service_account_compute_vm" {
  depends_on = [
    module.service-account-compute-vm-github-runners
  ]
  create_duration = "30s"
}

# Service Account for the Runners Manager (Cloud Run)
module "service-account-cloud-run-github-runners-manager" {
  source       = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/iam-service-account?ref=v49.1.0"
  project_id   = module.project.project_id
  name         = "github-runners-manager"
  display_name = "Cloud Run - GitHub Actions Runners manager (Terraform managed)"
  iam_project_roles = {
    (module.project.project_id) = [
      "roles/compute.admin",
      "roles/logging.logWriter",
      "roles/monitoring.metricWriter",
    ]
  }
}

# Wait for service account to be fully propagated in Google Cloud IAM
resource "time_sleep" "wait_for_service_account_cloud_run" {
  depends_on = [
    module.service-account-cloud-run-github-runners-manager
  ]
  create_duration = "30s"
}

# Service Account for Cloud Build (Image Creation)
module "service-account-cloud-build-github-runners" {
  source       = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/iam-service-account?ref=v50.0.0"
  project_id   = module.project.project_id
  name         = "cloud-build-github-runners"
  display_name = "Cloud Build - Create images (Terraform managed)"
  iam_project_roles = {
    (module.project.project_id) = [
      "roles/logging.logWriter",
    ]
  }
}

# Wait for service account to be fully propagated in Google Cloud IAM
resource "time_sleep" "wait_for_service_account_cloud_build" {
  depends_on = [
    module.service-account-cloud-build-github-runners
  ]
  create_duration = "30s"
}
