# Configure the Google Cloud project and enable required APIs
# https://github.com/GoogleCloudPlatform/cloud-foundation-fabric/blob/v49.1.0/modules/project/README.md
module "project" {
  source        = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/project?ref=v51.0.0"
  name          = var.project_id
  project_reuse = {}
  services      = var.apis
}