# Periodic reconciliation of queued GitHub jobs against runner VMs.
# Cloud Scheduler calls POST /reconcile on the manager with an OIDC token for the
# reconciler service account; the manager verifies audience and caller itself
# (the Cloud Run service has invoker IAM disabled so GitHub can reach the webhook).

locals {
  github_runners_manager_name = "github-runners-manager-${local.region_shortnames[var.region]}"
  # Deterministic Cloud Run URL, used as the OIDC audience so the service does not
  # have to reference its own generated URL (which would be a dependency cycle).
  # https://cloud.google.com/run/docs/triggering/https-request#deterministic
  github_runners_manager_audience = "https://${local.github_runners_manager_name}-${module.project.number}.${var.region}.run.app"
  # Minutes between passes, read from the "*/N * * * *" schedule (validated to that shape);
  # the reconciler uses it to gate reduced-rate retries of long-queued jobs.
  github_runners_reconcile_interval_minutes = can(regex("^\\*/(\\d+) \\* \\* \\* \\*$", var.github_runners_reconcile_schedule)) ? tonumber(regex("^\\*/(\\d+) \\* \\* \\* \\*$", var.github_runners_reconcile_schedule)[0]) : 5
}

# Service Account Cloud Scheduler uses to mint the OIDC token for the reconcile call
# https://github.com/GoogleCloudPlatform/cloud-foundation-fabric/blob/v53.0.0/modules/iam-service-account/README.md
module "service-account-github-runners-reconciler" {
  source       = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/iam-service-account?ref=v53.0.0"
  project_id   = module.project.project_id
  name         = "github-runners-reconciler"
  display_name = "Cloud Scheduler - GitHub Actions Runners reconciler (Terraform managed)"
}

# Wait for service account to be fully propagated in Google Cloud IAM
resource "time_sleep" "wait_for_service_account_reconciler" {
  depends_on = [
    module.service-account-github-runners-reconciler
  ]
  create_duration = "30s"
}

# https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_scheduler_job
resource "google_cloud_scheduler_job" "github-runners-reconcile" {
  project     = module.project.project_id
  region      = var.region
  name        = "github-runners-reconcile-${local.region_shortnames[var.region]}"
  description = "Reconcile queued GitHub Actions jobs with runner VMs (Terraform managed)"
  schedule    = var.github_runners_reconcile_schedule
  time_zone   = "Etc/UTC"
  # Must exceed the longest pass: creations wait for the insert operation and zone fallback.
  attempt_deadline = "${var.github_runners_reconcile_attempt_deadline}s"

  retry_config {
    retry_count = 0
  }

  http_target {
    http_method = "POST"
    uri         = "${module.cloud_run_github_runners_manager.service_uri}/reconcile"
    oidc_token {
      service_account_email = module.service-account-github-runners-reconciler.email
      audience              = local.github_runners_manager_audience
    }
  }

  depends_on = [
    module.project,
    time_sleep.wait_for_service_account_reconciler,
    module.cloud_run_github_runners_manager,
  ]
}
