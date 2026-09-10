# Cloud Tasks queue between webhook receipt and VM creation.
# The webhook enqueues one task per workflow job (task name = job id, so a redelivery cannot
# double-provision) and answers GitHub at once; the task calls POST /tasks/provision on the
# manager with an OIDC token for the provisioner service account, and the queue retries
# capacity errors with backoff. Tasks that exhaust their attempts are left to the reconciler.

# Service Account Cloud Tasks uses to call the manager
# https://github.com/GoogleCloudPlatform/cloud-foundation-fabric/blob/v53.0.0/modules/iam-service-account/README.md
module "service-account-github-runners-provisioner" {
  source       = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/iam-service-account?ref=v53.0.0"
  project_id   = module.project.project_id
  name         = "github-runners-provisioner"
  display_name = "Cloud Tasks - GitHub Actions Runners provisioner (Terraform managed)"
  iam = {
    # The manager attaches this identity to the tasks it creates, and the Cloud Tasks service
    # agent mints the OIDC token when it dispatches them.
    "roles/iam.serviceAccountUser" = [
      module.service-account-cloud-run-github-runners-manager.iam_email,
      "serviceAccount:service-${module.project.number}@gcp-sa-cloudtasks.iam.gserviceaccount.com",
    ]
  }
  depends_on = [
    module.project # the service agent exists once cloudtasks.googleapis.com is enabled
  ]
}

# Wait for service account to be fully propagated in Google Cloud IAM
resource "time_sleep" "wait_for_service_account_provisioner" {
  depends_on = [
    module.service-account-github-runners-provisioner
  ]
  create_duration = "30s"
}

# https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_tasks_queue
resource "google_cloud_tasks_queue" "github-runners-provision" {
  project  = module.project.project_id
  location = var.region
  name     = "github-runners-provision-${local.region_shortnames[var.region]}"

  rate_limits {
    # A ~100-job fan-out is spread over ~20 s; each task blocks ~10 s on the insert operation.
    max_dispatches_per_second = var.github_runners_provision_max_dispatches_per_second
    max_concurrent_dispatches = var.github_runners_provision_max_concurrent_dispatches
  }

  retry_config {
    # Capacity errors answer 503; retry with backoff, then hand off to the reconciler.
    max_attempts  = var.github_runners_provision_max_attempts
    min_backoff   = "30s"
    max_backoff   = "300s"
    max_doublings = 4
  }

  depends_on = [
    module.project
  ]
}

# The manager may enqueue tasks
# https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_tasks_queue_iam
resource "google_cloud_tasks_queue_iam_member" "github-runners-manager-enqueuer" {
  project  = google_cloud_tasks_queue.github-runners-provision.project
  location = google_cloud_tasks_queue.github-runners-provision.location
  name     = google_cloud_tasks_queue.github-runners-provision.name
  role     = "roles/cloudtasks.enqueuer"
  member   = module.service-account-cloud-run-github-runners-manager.iam_email
}
