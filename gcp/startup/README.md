# Startup Scripts

Startup scripts that run when a virtual machine (VM) instance boots:

* `install.sh` : Install Docker, Go (`GO_MINOR`, default `1.26`), GitHub CLI and the GitHub Actions runner during
  custom image creation. Also installs `gha-preempt-notify.service` (long-polls the metadata `preempted` flag) and
  `gha-preempt-notify-shutdown.service` (fires on ACPI shutdown of Spot VMs); both POST to the manager's
  `/runner/preempted` route with the VM's service-account OIDC token, using the `gha-manager-url`, `gha-job-id` and
  `gha-runner-name` instance metadata the manager stamps at creation.
