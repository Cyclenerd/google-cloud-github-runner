# VPC for GitHub Actions Runners
# https://github.com/GoogleCloudPlatform/cloud-foundation-fabric/blob/v53.0.0/modules/net-vpc/README.md
module "vpc-github-runners" {
  source      = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/net-vpc?ref=v53.0.0"
  project_id  = module.project.project_id
  name        = "vpc-github-runners"
  description = "VPC for GitHub Actions Runners (Terraform-managed)"
  subnets = [
    {
      ip_cidr_range = "100.64.0.0/16" # https://en.wikipedia.org/wiki/Carrier-grade_NAT
      name          = "subnet-github-runners-${local.region_shortnames[var.region]}"
      region        = var.region
      description   = "Subnet for GitHub Actions Runners in ${var.region} (Terraform-managed)"
    }
  ]
}

# Firewall rules for GitHub Actions Runners
# https://github.com/GoogleCloudPlatform/cloud-foundation-fabric/tree/v53.0.0/modules/net-vpc-firewall
module "firewall-github-runners" {
  source               = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/net-vpc-firewall?ref=v53.0.0"
  project_id           = module.project.project_id
  network              = module.vpc-github-runners.name
  default_rules_config = { disabled = true }
  ingress_rules = {
    allow-ssh-from-iap = {
      description   = "Enable SSH from IAP (Terraform-managed)"
      source_ranges = ["35.235.240.0/20"]
      rules         = [{ protocol = "tcp", ports = [22] }]
    }
  }
}
