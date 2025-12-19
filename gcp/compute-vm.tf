locals {
  github_runners_types_map = {
    for type in var.github_runners_types : type.name => type
  }
}

# Create instance templates for each GitHub Actions runner type
# https://github.com/GoogleCloudPlatform/cloud-foundation-fabric/blob/v49.1.0/modules/compute-vm/README.md
module "github-runners-vm-templates" {
  source   = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric//modules/compute-vm?ref=v49.1.0"
  for_each = local.github_runners_types_map

  project_id = module.project.project_id
  zone       = "${var.region}-${var.zone}"

  name          = each.value.name
  description   = "GitHub Actions runner template (${upper(each.value.arch)}), ${each.value.vcpu} vCPU, ${each.value.memory} GB memory, ${each.value.disk_size} GB SSD (Terraform-managed)"
  instance_type = each.value.instance_type

  network_interfaces = [{
    network    = module.vpc-github-runners.self_link
    subnetwork = module.vpc-github-runners.subnet_self_links["${var.region}/subnet-github-runners-${local.region_shortnames[var.region]}"]
  }]

  boot_disk = {
    initialize_params = {
      image = "projects/${module.project.project_id}/global/images/family/${each.value.image}" # Build via build-image-[...].sh
      type  = each.value.disk_type
      size  = each.value.disk_size
      # For hyperdisk-balanced
      provisioned_iops       = each.value.disk_provisioned_iops
      provisioned_throughput = each.value.disk_provisioned_throughput
    }
  }

  service_account = {
    auto_create = false
    email       = module.service-account-compute-vm-github-runners.email
  }

  metadata = {
    startup-script = "# Overwritten by the GitHub Actions Runners manager during creation."
  }

  create_template = {
    regional = true
  }

  depends_on = [
    null_resource.build-github-runners-images,
    time_sleep.wait_for_service_account_compute_vm
  ]
}
