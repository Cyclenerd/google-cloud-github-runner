# Google Cloud APIs to enable for the project
variable "apis" {
  description = "List of Google Cloud APIs to be enable"
  type        = list(string)
  default = [
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "orgpolicy.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ]
}

# Google Cloud project ID where resources will be created
variable "project_id" {
  description = "Existing Google Cloud project ID"
  type        = string
  nullable    = false

  # https://cloud.google.com/resource-manager/docs/creating-managing-projects#before_you_begin
  validation {
    # Must be 6 to 30 characters in length.
    # Can only contain lowercase letters, numbers, and hyphens.
    # Must start with a letter.
    # Cannot end with a hyphen.
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Invalid Google Cloud project ID!"
  }
}

# Google Cloud region for deploying resources
variable "region" {
  description = "Google Cloud region name"
  type        = string
  default     = "us-central1"
  nullable    = false

  validation {
    condition     = can(regex("^[a-z][-a-z]+[0-9]$", var.region))
    error_message = "Invalid Google Cloud region name!"
  }

}

# Zone suffix (a-f) within the region
variable "zone" {
  description = "Google Cloud zone suffix"
  type        = string
  default     = "b"
  nullable    = false

  validation {
    condition     = contains(["a", "b", "c", "d", "e", "f"], var.zone)
    error_message = "Zone suffix must be one of: a, b, c, d, e, f."
  }
}

# Minimum number of Cloud Run instances for the GitHub Actions Runners manager application
# Unfortunately, the Cloud Run cold start time is slow and often exceeds 30 seconds.
# GitHub expects a response to webhook requests in under 10 seconds!
# https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks#respond-within-10-seconds
# Therefore, we always have to have one instance running and cannot scale to 0.
variable "github_runners_manager_min_instance_count" {
  description = "GitHub Actions Runners manager app min. instance count (a minimum of one Cloud Run instance is required to avoid GitHub webhook timeout!)"
  type        = number
  default     = 1

  validation {
    condition     = var.github_runners_manager_min_instance_count >= 1
    error_message = "Maximum instance count must be larger than or equal 1 to avoid GitHub webhook timeout!"
  }
}

# Maximum number of Cloud Run instances for the GitHub Actions Runners manager application
variable "github_runners_manager_max_instance_count" {
  description = "GitHub Actions Runners manager app maximum instance count (Max. number of Cloud Run instances)"
  type        = number
  default     = 1

  validation {
    condition     = var.github_runners_manager_max_instance_count >= var.github_runners_manager_min_instance_count
    error_message = "Maximum instance count must be larger than or equal to github_runners_manager_min_instance_count."
  }
}

# Map of default VM images for GitHub Actions Runners by architecture
variable "github_runners_default_image" {
  description = "Default GitHub Actions Runners images (family images) for different CPU architectures"
  type        = map(string)
  default = {
    ubuntu-2404-lts-arm64 = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-arm64"
    ubuntu-2404-lts-amd64 = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64"
    ubuntu-2204-lts-arm64 = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts-arm64"
    ubuntu-2204-lts-amd64 = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts" # Without "-amd64" suffix
  }

  validation {
    condition = alltrue([
      for key, value in var.github_runners_default_image :
      can(regex("projects/.*/images/family/.*", value))
    ])
    error_message = "All image_family URIs must contain 'projects/' and 'images/family/'."
  }

  validation {
    condition = alltrue([
      for key, value in var.github_runners_default_image :
      can(regex("^[a-zA-Z0-9-]+$", key))
    ])
    error_message = "Keys must only contain letters, numbers, and hyphens."
  }
}

# Default instance types for building runner images by CPU architecture
variable "github_runners_default_type" {
  description = "Default GitHub Actions Runners instance types for different CPU architectures"
  type = object({
    amd64 = object({
      instance_type               = string
      disk_type                   = string
      disk_size                   = number
      disk_provisioned_iops       = number
      disk_provisioned_throughput = number
    })
    arm64 = object({
      instance_type               = string
      disk_type                   = string
      disk_size                   = number
      disk_provisioned_iops       = number
      disk_provisioned_throughput = number
    })
  })
  default = {
    amd64 = {
      instance_type               = "e2-standard-4"
      disk_type                   = "pd-ssd"
      disk_size                   = 10
      disk_provisioned_iops       = 0
      disk_provisioned_throughput = 0
    }
    arm64 = {
      instance_type               = "c4a-standard-4"
      disk_type                   = "hyperdisk-balanced"
      disk_size                   = 10
      disk_provisioned_iops       = 3060
      disk_provisioned_throughput = 155
    }
  }

  validation {
    condition = alltrue([
      for value in values(var.github_runners_default_type) :
      can(regex("^[a-zA-Z0-9-]+$", value.instance_type))
    ])
    error_message = "Instance type values must only contain letters, numbers, and hyphens."
  }

  validation {
    condition = alltrue([
      for value in values(var.github_runners_default_type) :
      contains(["pd-ssd", "hyperdisk-balanced"], value.disk_type)
    ])
    error_message = "Disk type must be either 'pd-ssd' or 'hyperdisk-balanced'."
  }

  validation {
    condition = alltrue([
      for value in values(var.github_runners_default_type) :
      value.disk_size >= 10
    ])
    error_message = "Disk size must be larger than or equal to 10 GB."
  }

  validation {
    condition = alltrue([
      for value in values(var.github_runners_default_type) :
      value.disk_type != "hyperdisk-balanced" || (value.disk_provisioned_iops > 3000 && value.disk_provisioned_throughput > 140)
    ])
    error_message = "For hyperdisk-balanced, disk_provisioned_iops must be larger than 3000 and disk_provisioned_throughput must be larger than 140."
  }
}

# List of GitHub Actions runner configurations with instance specs
variable "github_runners_types" {
  description = "GitHub Actions Runners instance types for different CPU architectures"
  type = list(object({
    name                        = string
    instance_type               = string
    vcpu                        = number
    memory                      = number
    disk_type                   = string
    disk_size                   = number
    disk_provisioned_iops       = number
    disk_provisioned_throughput = number
    image                       = string
    arch                        = string
  }))
  # Similar to https://docs.github.com/en/enterprise-cloud@latest/actions/reference/runners/larger-runners
  default = [
    {
      name                        = "gcp-ubuntu-slim"
      instance_type               = "e2-medium"
      vcpu                        = 2
      memory                      = 4
      disk_type                   = "pd-ssd"
      disk_size                   = 15
      disk_provisioned_iops       = 0
      disk_provisioned_throughput = 0
      image                       = "ubuntu-2404-lts-amd64"
      arch                        = "amd64"
    },
    {
      name                        = "gcp-ubuntu-latest"
      instance_type               = "e2-standard-4"
      vcpu                        = 4
      memory                      = 16
      disk_type                   = "pd-ssd"
      disk_size                   = 25
      disk_provisioned_iops       = 0
      disk_provisioned_throughput = 0
      image                       = "ubuntu-2404-lts-amd64"
      arch                        = "amd64"
    },
    {
      name                        = "gcp-ubuntu-24-04"
      instance_type               = "e2-standard-4"
      vcpu                        = 4
      memory                      = 16
      disk_type                   = "pd-ssd"
      disk_size                   = 25
      disk_provisioned_iops       = 0
      disk_provisioned_throughput = 0
      image                       = "ubuntu-2404-lts-amd64"
      arch                        = "amd64"
    },
    {
      name                        = "gcp-ubuntu-24-04-2core"
      instance_type               = "e2-standard-2"
      vcpu                        = 2
      memory                      = 8
      disk_type                   = "pd-ssd"
      disk_size                   = 75
      disk_provisioned_iops       = 0
      disk_provisioned_throughput = 0
      image                       = "ubuntu-2404-lts-amd64"
      arch                        = "amd64"
    },
    {
      name                        = "gcp-ubuntu-24-04-4core"
      instance_type               = "e2-standard-4"
      vcpu                        = 4
      memory                      = 16
      disk_type                   = "pd-ssd"
      disk_size                   = 150
      disk_provisioned_iops       = 0
      disk_provisioned_throughput = 0
      image                       = "ubuntu-2404-lts-amd64"
      arch                        = "amd64"
    },
    {
      name                        = "gcp-ubuntu-24-04-8core"
      instance_type               = "e2-standard-8"
      vcpu                        = 8
      memory                      = 32
      disk_type                   = "pd-ssd"
      disk_size                   = 300
      disk_provisioned_iops       = 0
      disk_provisioned_throughput = 0
      image                       = "ubuntu-2404-lts-amd64"
      arch                        = "amd64"
    },
    {
      name                        = "gcp-ubuntu-24-04-16core"
      instance_type               = "e2-standard-16"
      vcpu                        = 16
      memory                      = 64
      disk_type                   = "pd-ssd"
      disk_size                   = 600
      disk_provisioned_iops       = 0
      disk_provisioned_throughput = 0
      image                       = "ubuntu-2404-lts-amd64"
      arch                        = "amd64"
    },
    {
      name                        = "gcp-ubuntu-24-04-32core"
      instance_type               = "e2-standard-32"
      vcpu                        = 32
      memory                      = 128
      disk_type                   = "pd-ssd"
      disk_size                   = 1200
      disk_provisioned_iops       = 0
      disk_provisioned_throughput = 0
      image                       = "ubuntu-2404-lts-amd64"
      arch                        = "amd64"
    },
    {
      name                        = "gcp-ubuntu-24-04-64core"
      instance_type               = "e2-standard-64"
      vcpu                        = 64
      memory                      = 256
      disk_type                   = "pd-ssd"
      disk_size                   = 2040
      disk_provisioned_iops       = 0
      disk_provisioned_throughput = 0
      image                       = "ubuntu-2404-lts-amd64"
      arch                        = "amd64"
    },
    {
      name                        = "gcp-ubuntu-24-04-96core"
      instance_type               = "n2d-standard-96"
      vcpu                        = 96
      memory                      = 384
      disk_type                   = "pd-ssd"
      disk_size                   = 2040
      disk_provisioned_iops       = 0
      disk_provisioned_throughput = 0
      image                       = "ubuntu-2404-lts-amd64"
      arch                        = "amd64"
    },
    {
      name                        = "gcp-ubuntu-24-04-128core"
      instance_type               = "n2d-standard-128"
      vcpu                        = 128
      memory                      = 512
      disk_type                   = "pd-ssd"
      disk_size                   = 2040
      disk_provisioned_iops       = 0
      disk_provisioned_throughput = 0
      image                       = "ubuntu-2404-lts-amd64"
      arch                        = "amd64"
    },
    {
      name                        = "gcp-ubuntu-slim-arm"
      instance_type               = "c4a-standard-1"
      vcpu                        = 1
      memory                      = 4
      disk_type                   = "hyperdisk-balanced"
      disk_size                   = 15
      disk_provisioned_iops       = 3090
      disk_provisioned_throughput = 162
      image                       = "ubuntu-2404-lts-arm64"
      arch                        = "arm64"
    },
    {
      name                        = "gcp-ubuntu-latest-arm"
      instance_type               = "c4a-standard-4"
      vcpu                        = 4
      memory                      = 16
      disk_type                   = "hyperdisk-balanced"
      disk_size                   = 25
      disk_provisioned_iops       = 3150
      disk_provisioned_throughput = 177
      image                       = "ubuntu-2404-lts-arm64"
      arch                        = "arm64"
    },
    {
      name                        = "gcp-ubuntu-24-04-arm"
      instance_type               = "c4a-standard-4"
      vcpu                        = 4
      memory                      = 16
      disk_type                   = "hyperdisk-balanced"
      disk_size                   = 25
      disk_provisioned_iops       = 3150
      disk_provisioned_throughput = 177
      image                       = "ubuntu-2404-lts-arm64"
      arch                        = "arm64"
    },
    {
      name                        = "gcp-ubuntu-24-04-2core-arm"
      instance_type               = "c4a-standard-2"
      vcpu                        = 2
      memory                      = 8
      disk_type                   = "hyperdisk-balanced"
      disk_size                   = 75
      disk_provisioned_iops       = 3450
      disk_provisioned_throughput = 252
      image                       = "ubuntu-2404-lts-arm64"
      arch                        = "arm64"
    },
    {
      name                        = "gcp-ubuntu-24-04-4core-arm"
      instance_type               = "c4a-standard-4"
      vcpu                        = 4
      memory                      = 16
      disk_type                   = "hyperdisk-balanced"
      disk_size                   = 150
      disk_provisioned_iops       = 3900
      disk_provisioned_throughput = 365
      image                       = "ubuntu-2404-lts-arm64"
      arch                        = "arm64"
    },
    {
      name                        = "gcp-ubuntu-24-04-8core-arm"
      instance_type               = "c4a-standard-8"
      vcpu                        = 8
      memory                      = 32
      disk_type                   = "hyperdisk-balanced"
      disk_size                   = 300
      disk_provisioned_iops       = 4800
      disk_provisioned_throughput = 590
      image                       = "ubuntu-2404-lts-arm64"
      arch                        = "arm64"
    },
    {
      name                        = "gcp-ubuntu-24-04-16core-arm"
      instance_type               = "c4a-standard-16"
      vcpu                        = 16
      memory                      = 64
      disk_type                   = "hyperdisk-balanced"
      disk_size                   = 600
      disk_provisioned_iops       = 6600
      disk_provisioned_throughput = 1040
      image                       = "ubuntu-2404-lts-arm64"
      arch                        = "arm64"
    },
    {
      name                        = "gcp-ubuntu-24-04-32core-arm"
      instance_type               = "c4a-standard-32"
      vcpu                        = 32
      memory                      = 128
      disk_type                   = "hyperdisk-balanced"
      disk_size                   = 1200
      disk_provisioned_iops       = 10200
      disk_provisioned_throughput = 1940
      image                       = "ubuntu-2404-lts-arm64"
      arch                        = "arm64"
    },
    {
      name                        = "gcp-ubuntu-24-04-64core-arm"
      instance_type               = "c4a-standard-64"
      vcpu                        = 64
      memory                      = 256
      disk_type                   = "hyperdisk-balanced"
      disk_size                   = 2040
      disk_provisioned_iops       = 15240
      disk_provisioned_throughput = 2400
      image                       = "ubuntu-2404-lts-arm64"
      arch                        = "arm64"
    },
    {
      name                        = "gcp-ubuntu-24-04-72core-arm"
      instance_type               = "c4a-standard-72"
      vcpu                        = 72
      memory                      = 288
      disk_type                   = "hyperdisk-balanced"
      disk_size                   = 2040
      disk_provisioned_iops       = 15240
      disk_provisioned_throughput = 2400
      image                       = "ubuntu-2404-lts-arm64"
      arch                        = "arm64"
    },
  ]

  validation {
    condition = alltrue([
      for config in var.github_runners_types :
      config.vcpu > 0 && config.memory > 0 && config.disk_size >= 10
    ])
    error_message = "All vcpu and memory values must be greater than 0, and disk_size must be larger than or equal to 10."
  }

  validation {
    condition = alltrue([
      for config in var.github_runners_types :
      can(regex("^gcp-[a-zA-Z0-9-]+$", config.name))
    ])
    error_message = "All names must start with 'gcp-' and only contain letters, numbers and hyphens."
  }

  validation {
    condition = length([
      for config in var.github_runners_types : config.name
      ]) == length(distinct([
        for config in var.github_runners_types : config.name
    ]))
    error_message = "All instance names must be unique."
  }

  validation {
    condition = alltrue([
      for config in var.github_runners_types :
      can(regex("^[a-zA-Z0-9-]+$", config.instance_type))
    ])
    error_message = "All instance_type values must only contain letters, numbers, and hyphens."
  }

  validation {
    condition = alltrue([
      for config in var.github_runners_types :
      contains(["pd-ssd", "hyperdisk-balanced"], config.disk_type)
    ])
    error_message = "Disk type must be either 'pd-ssd' or 'hyperdisk-balanced'."
  }

  validation {
    condition = alltrue([
      for config in var.github_runners_types :
      config.disk_type != "hyperdisk-balanced" || (config.disk_provisioned_iops > 3000 && config.disk_provisioned_throughput > 140)
    ])
    error_message = "For hyperdisk-balanced, disk_provisioned_iops must be larger than 3000 and disk_provisioned_throughput must be larger than 140."
  }

  validation {
    condition = alltrue([
      for config in var.github_runners_types :
      contains(keys(var.github_runners_default_image), config.image)
    ])
    error_message = "All image values must exist as keys in github_runners_default_image."
  }

  validation {
    condition = alltrue([
      for config in var.github_runners_types :
      contains(["amd64", "arm64"], config.arch)
    ])
    error_message = "All arch values must be either 'amd64' or 'arm64'."
  }
}
