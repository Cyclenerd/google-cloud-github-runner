# https://github.com/GoogleCloudPlatform/cloud-foundation-fabric/blob/v49.1.0/modules/gcs/README.md

# GCS bucket for storing Terraform state
module "gcs-github-runners-iac" {
  source        = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/gcs?ref=v49.1.0"
  project_id    = module.project.project_id
  prefix        = module.project.project_id
  name          = "gh-iac-${local.region_shortnames[var.region]}"
  location      = var.region
  versioning    = true
  force_destroy = true
}

# GCS bucket for Cloud Build source staging
module "gcs-github-runners-cloud-build" {
  source        = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/gcs?ref=v49.1.0"
  project_id    = module.project.project_id
  prefix        = module.project.project_id
  name          = "build-${local.region_shortnames[var.region]}"
  location      = var.region
  versioning    = false
  force_destroy = true
  lifecycle_rules = {
    lr-0 = {
      action = {
        type = "Delete"
      }
      condition = {
        age        = 2
        with_state = "ANY"
      }
    }
  }
  iam = {
    "roles/storage.objectAdmin" = [
      module.service-account-cloud-build-github-runners.iam_email
    ]
  }
  depends_on = [
    time_sleep.wait_for_service_account_cloud_build
  ]
}

# GCS bucket for storing the VM startup script
module "gcs-github-runners-startup-script" {
  source        = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/gcs?ref=v49.1.0"
  project_id    = module.project.project_id
  prefix        = module.project.project_id
  name          = "gh-start-${local.region_shortnames[var.region]}"
  location      = var.region
  versioning    = false
  force_destroy = true
  iam = {
    "roles/storage.objectViewer" = [
      module.service-account-compute-vm-github-runners.iam_email
    ]
  }
  depends_on = [
    time_sleep.wait_for_service_account_compute_vm
  ]
}
