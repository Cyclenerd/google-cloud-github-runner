# Cloud NAT for GitHub Actions Runners to access the internet
# https://github.com/GoogleCloudPlatform/cloud-foundation-fabric/blob/v49.1.0/modules/net-cloudnat/README.md
module "nat-github-runners" {
  source         = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/net-cloudnat?ref=v49.1.0"
  project_id     = module.project.project_id
  region         = var.region
  name           = "cloudnat-github-runners-${local.region_shortnames[var.region]}"
  router_network = module.vpc-github-runners.self_link
}
