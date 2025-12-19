# Startup script for GitHub Actions Runners
# https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/storage_bucket_object
resource "google_storage_bucket_object" "github-runners-startup-script" {
  bucket = module.gcs-github-runners-startup-script.name
  name   = "startup/install.sh"
  source = "${path.module}/startup/install.sh"
}
