# Service URL of the GitHub Actions Runners manager (Cloud Run)
# https://github.com/GoogleCloudPlatform/cloud-foundation-fabric/blob/v53.0.0/modules/cloud-run-v2/README.md#outputs
output "github_runners_manager_url" {
  value = module.cloud_run_github_runners_manager.service_uri
}

# Generate Cloud Build configuration for building the manager container image
resource "local_file" "cloudbuild-github-runners-manager-config" {
  filename        = "${path.module}/cloudbuild-container.yaml"
  file_permission = "0640"
  content = templatefile("${path.module}/cloudbuild-container.template.yaml", {
    repository_url        = module.artifact-registry-container.url,
    build_service_account = module.service-account-cloud-build-github-runners.id # Not email
  })
}

# Generate shell script to trigger Cloud Build for the manager container image
resource "local_file" "cloudbuild-github-runners-manager-script" {
  filename        = "${path.module}/build-container.sh"
  file_permission = "0750"
  content = templatefile("${path.module}/build-container.template.sh", {
    region     = var.region
    project_id = module.project.project_id
    bucket     = module.gcs-github-runners-cloud-build.name
  })
}

# Trigger the build of the manager container image when relevant files change
resource "null_resource" "build-github-runners-manager-container" {
  triggers = {
    script_hash     = sha256(local_file.cloudbuild-github-runners-manager-script.content)
    config_hash     = sha256(local_file.cloudbuild-github-runners-manager-config.content)
    dockerfile_hash = sha256(file("${path.module}/../Dockerfile"))
  }

  provisioner "local-exec" {
    command = local_file.cloudbuild-github-runners-manager-script.filename
  }

  depends_on = [
    module.project,
    module.service-account-cloud-build-github-runners,
    time_sleep.wait_for_service_account_cloud_build,
    module.artifact-registry-container,
    module.gcs-github-runners-cloud-build,
  ]
}

# Generate providers.tf for GCS backend (helper for migration/setup)
resource "local_file" "terraform-providers-file-gcs" {
  filename        = "${path.module}/providers.tf.gcs"
  file_permission = "0640"
  content = templatefile("${path.module}/providers.tf.template", {
    bucket = module.gcs-github-runners-iac.name
  })
}

# Generate shell scripts to build GCE VM images for each runner type
resource "local_file" "github-runners-images" {
  for_each = toset(distinct([
    for runner in var.github_runners_types : runner.image
  ]))

  filename        = "${path.module}/build-image-${each.value}.sh"
  file_permission = "0750"
  content = templatefile("${path.module}/build-image.template.sh", {
    service_account             = module.service-account-compute-vm-github-runners.email
    image_name                  = each.value
    image_family                = var.github_runners_default_image[each.value]
    startup_script_gcs          = "${module.gcs-github-runners-startup-script.url}/${google_storage_bucket_object.github-runners-startup-script.output_name}"
    machine_type                = can(regex("arm64", each.value)) ? var.github_runners_default_type["arm64"].instance_type : var.github_runners_default_type["amd64"].instance_type
    disk_type                   = can(regex("arm64", each.value)) ? var.github_runners_default_type["arm64"].disk_type : var.github_runners_default_type["amd64"].disk_type
    disk_size                   = can(regex("arm64", each.value)) ? var.github_runners_default_type["arm64"].disk_size : var.github_runners_default_type["amd64"].disk_size
    disk_provisioned_iops       = can(regex("arm64", each.value)) ? var.github_runners_default_type["arm64"].disk_provisioned_iops : var.github_runners_default_type["amd64"].disk_provisioned_iops
    disk_provisioned_throughput = can(regex("arm64", each.value)) ? var.github_runners_default_type["arm64"].disk_provisioned_throughput : var.github_runners_default_type["amd64"].disk_provisioned_throughput
    zone                        = "${var.region}-${var.zone}"
    region                      = var.region
    project_id                  = module.project.project_id
    subnet                      = module.vpc-github-runners.subnet_self_links["${var.region}/subnet-github-runners-${local.region_shortnames[var.region]}"]
  })
}

# Trigger the build of GCE VM images when the build scripts change
resource "null_resource" "build-github-runners-images" {
  for_each = local_file.github-runners-images

  triggers = {
    script_hash = sha256(each.value.content)
  }

  provisioner "local-exec" {
    command = each.value.filename
  }

  depends_on = [
    module.project,
    module.nat-github-runners,
    module.service-account-compute-vm-github-runners,
    time_sleep.wait_for_service_account_compute_vm,
    module.gcs-github-runners-startup-script,
    google_storage_bucket_object.github-runners-startup-script,
  ]
}
