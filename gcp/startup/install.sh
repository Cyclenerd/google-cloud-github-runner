#!/usr/bin/env bash

# Copyright 2025-2026 Nils Knieling. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Install Docker, Go, GitHub CLI and the GitHub Actions Runner for Linux with x64 or ARM64 CPU architecture,
# plus a systemd notifier that reports Spot preemptions to the runners manager
# https://github.com/actions/runner
# https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/about-self-hosted-runners#linux
# https://docs.docker.com/engine/install/ubuntu/

# Exit on error, undefined variables, and pipe failures
set -euo pipefail

# Set default GitHub Actions Runner installation directory
readonly MY_RUNNER_DIR="/actions-runner"

# Prevent interactive prompts during package installation
export DEBIAN_FRONTEND=noninteractive

# Function to exit the script with a failure message
exit_with_failure() {
	echo >&2 "FAILURE: $1"
	exit 1
}

# Detect CPU architecture early
case $(uname -m) in
	aarch64|arm64)
		readonly MY_ARCH="arm64"
		;;
	amd64|x86_64)
		readonly MY_ARCH="x64"
		;;
	*)
		exit_with_failure "Cannot determine CPU architecture!"
		;;
esac

# Install dependencies
echo "Installing system dependencies..."
sudo apt-get update -yq
sudo apt-get install -y \
	apt-transport-https \
	apt-utils \
	build-essential \
	ca-certificates \
	curl \
	dnsutils \
	git \
	gpg \
	jq \
	lsb-release \
	nodejs \
	npm \
	openssh-client \
	python3-crcmod \
	python3-openssl \
	python3-pip \
	python3-venv \
	software-properties-common \
	tar \
	unzip \
	zip

# Verify required commands are available
readonly REQUIRED_COMMANDS=(curl gzip jq sed tar)
for cmd in "${REQUIRED_COMMANDS[@]}"; do
	if ! command -v "$cmd" >/dev/null 2>&1; then
		exit_with_failure "Required command '$cmd' not found"
	fi
done

# Add Docker repository and install
echo "Installing Docker..."
sudo curl -fsSL "https://download.docker.com/linux/ubuntu/gpg" | sudo gpg --dearmor -o "/usr/share/keyrings/download.docker.com"
echo "deb [signed-by=/usr/share/keyrings/download.docker.com] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee "/etc/apt/sources.list.d/docker.list" >/dev/null
sudo apt-get update -yq
sudo apt-get install -y \
	docker-ce \
	docker-ce-cli \
	containerd.io \
	docker-buildx-plugin \
	docker-compose-plugin

# Enable and start Docker service
sudo systemctl enable docker.service
sudo systemctl start docker.service

# Create runner user and add to docker und sudoers group
echo "Creating runner user..."
if ! id -u runner >/dev/null 2>&1; then
	sudo useradd -m runner
fi
sudo usermod -aG docker,google-sudoers runner

# Install GitHub Actions Runner
echo "Installing GitHub Actions Runner..."
MY_RUNNER_VERSION=$(curl -fsSL "https://api.github.com/repos/actions/runner/releases/latest" | jq -r '.tag_name' | sed 's/^v//')
if [[ -z "$MY_RUNNER_VERSION" || "$MY_RUNNER_VERSION" == "null" ]]; then
	exit_with_failure "Could not retrieve the latest GitHub Actions Runner version"
fi
echo "Installing GitHub Actions Runner version: v${MY_RUNNER_VERSION}"

# Download and extract runner
sudo mkdir -p "$MY_RUNNER_DIR"
cd "$MY_RUNNER_DIR"
sudo curl -fsSL -O "https://github.com/actions/runner/releases/download/v${MY_RUNNER_VERSION}/actions-runner-linux-${MY_ARCH}-${MY_RUNNER_VERSION}.tar.gz"
sudo tar xzf "actions-runner-linux-${MY_ARCH}-${MY_RUNNER_VERSION}.tar.gz"

# Run the installation script
sudo ./bin/installdependencies.sh
echo "GitHub Actions Runner installed successfully"

# Install the Go toolchain (latest patch of the wanted minor) into /usr/local/go.
# Workflows still run actions/setup-go; this copy is for tools that shell out to `go`
# without a setup step (e.g. tests calling the toolchain from Python).
# https://go.dev/doc/install
readonly MY_GO_MINOR="${GO_MINOR:-1.26}"
echo "Installing Go ${MY_GO_MINOR}.x..."
case $MY_ARCH in
	x64) MY_GO_ARCH="amd64" ;;
	*) MY_GO_ARCH="$MY_ARCH" ;;
esac
MY_GO_VERSION=$(curl -fsSL "https://go.dev/dl/?mode=json&include=all" \
	| jq -r --arg minor "go${MY_GO_MINOR}." '[.[] | select(.stable == true and (.version | startswith($minor)))] | .[0].version // empty')
if [[ -z "$MY_GO_VERSION" ]]; then
	echo "No stable Go ${MY_GO_MINOR}.x release found, falling back to the latest stable release"
	MY_GO_VERSION=$(curl -fsSL "https://go.dev/dl/?mode=json" | jq -r '[.[] | select(.stable == true)] | .[0].version // empty')
fi
if [[ -z "$MY_GO_VERSION" ]]; then
	exit_with_failure "Could not determine the Go version to install"
fi
echo "Installing Go version: ${MY_GO_VERSION}"
MY_GO_ARCHIVE="${MY_GO_VERSION}.linux-${MY_GO_ARCH}.tar.gz"
curl -fsSL -o "/tmp/${MY_GO_ARCHIVE}" "https://go.dev/dl/${MY_GO_ARCHIVE}"
MY_GO_SHA256=$(curl -fsSL "https://go.dev/dl/?mode=json&include=all" \
	| jq -r --arg file "$MY_GO_ARCHIVE" '.[].files[] | select(.filename == $file) | .sha256' | head -n 1)
if [[ -n "$MY_GO_SHA256" ]]; then
	echo "${MY_GO_SHA256}  /tmp/${MY_GO_ARCHIVE}" | sha256sum -c - || exit_with_failure "Go archive checksum mismatch"
fi
sudo rm -rf /usr/local/go
sudo tar -C /usr/local -xzf "/tmp/${MY_GO_ARCHIVE}"
rm -f "/tmp/${MY_GO_ARCHIVE}"
# Login shells
sudo tee /etc/profile.d/go.sh >/dev/null <<'PROFILE'
export GOPATH="$HOME/go"
export PATH="/usr/local/go/bin:$HOME/go/bin:$PATH"
PROFILE
# Job steps: the runner is started with `sudo -u runner`, which resets PATH to sudo's
# secure_path, and the runner records that PATH (.path) for every job step.
# Include Go and the runner user's GOPATH/bin there.
sudo tee /etc/sudoers.d/gha-runner-path >/dev/null <<'SUDOERS'
Defaults secure_path="/usr/local/go/bin:/home/runner/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin"
SUDOERS
sudo chmod 0440 /etc/sudoers.d/gha-runner-path
sudo visudo -cf /etc/sudoers.d/gha-runner-path >/dev/null || exit_with_failure "Invalid sudoers drop-in"
/usr/local/go/bin/go version || exit_with_failure "Go installation failed"

# Install GitHub CLI
# https://github.com/cli/cli/blob/trunk/docs/install_linux.md
echo "Installing GitHub CLI..."
sudo mkdir -p -m 755 /etc/apt/keyrings
sudo curl -fsSL "https://cli.github.com/packages/githubcli-archive-keyring.gpg" -o /etc/apt/keyrings/githubcli-archive-keyring.gpg
sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
sudo apt-get update -yq
sudo apt-get install -y gh
gh --version || exit_with_failure "GitHub CLI installation failed"

# Verify the commands job steps call without a setup action are on the image
readonly RUNNER_COMMANDS=(docker gh git go jq node npm pip3 python3)
for cmd in "${RUNNER_COMMANDS[@]}"; do
	if ! PATH="/usr/local/go/bin:$PATH" command -v "$cmd" >/dev/null 2>&1; then
		exit_with_failure "Runner command '$cmd' not found on the image"
	fi
done
echo "Free disk on the boot disk after installation (margin for module caches and container images):"
df -h /

# Preemption notice: report a Spot reclaim (metadata flag or ACPI shutdown) to the manager.
# The manager stamps gha-manager-url / gha-job-id / gha-runner-name into the instance
# metadata at creation; VMs without gha-manager-url (e.g. this image builder) stay silent.
# https://cloud.google.com/compute/docs/instances/create-use-spot#detect-preemption
echo "Installing preemption notifier..."
sudo tee /usr/local/bin/gha-preempt-notify.sh >/dev/null <<'NOTIFY'
#!/usr/bin/env bash
# Report a Spot preemption (metadata flag) or a shutdown of this runner VM to the manager.
# Usage: gha-preempt-notify.sh watch|shutdown
set -u
MODE="${1:-watch}"
MD="http://metadata.google.internal/computeMetadata/v1"
MARKER="/run/gha-preempt-notified"

md() {
	# $2: curl max-time (default 5 s; the long-poll passes a value above its timeout_sec)
	curl -sf -m "${2:-5}" -H "Metadata-Flavor: Google" "$MD/$1"
}

MANAGER_URL=$(md "instance/attributes/gha-manager-url" 2>/dev/null) || exit 0
[ -n "$MANAGER_URL" ] || exit 0
INSTANCE_NAME=$(md "instance/name")
ZONE=$(md "instance/zone" | awk -F/ '{print $NF}')
JOB_ID=$(md "instance/attributes/gha-job-id" 2>/dev/null || true)
RUNNER_NAME=$(md "instance/attributes/gha-runner-name" 2>/dev/null || echo "$INSTANCE_NAME")
PREEMPTIBLE=$(md "instance/scheduling/preemptible" 2>/dev/null || echo "FALSE")

notify() {
	local reason="$1"
	[ -e "$MARKER" ] && return 0
	local preempted runner_active token body attempt
	preempted=$(md "instance/preempted" 2>/dev/null || echo "UNKNOWN")
	# An ephemeral runner removes its registration files once its job is done, so their
	# presence means a job is still running (or the runner never got to run one); the process
	# check is a fallback in case units are being stopped in parallel at shutdown.
	runner_active="false"
	if [ -f /actions-runner/.runner ] || pgrep -f "Runner.Listener" >/dev/null 2>&1; then
		runner_active="true"
	fi
	token=$(md "instance/service-accounts/default/identity?audience=${MANAGER_URL}&format=full" 2>/dev/null || true)
	body=$(printf '{"reason":"%s","instance_name":"%s","zone":"%s","runner_name":"%s","job_id":"%s","preempted":"%s","preemptible":"%s","runner_active":%s}' \
		"$reason" "$INSTANCE_NAME" "$ZONE" "$RUNNER_NAME" "$JOB_ID" "$preempted" "$PREEMPTIBLE" "$runner_active")
	for attempt in 1 2; do
		if curl -sf -m 5 -X POST \
			-H "Authorization: Bearer ${token}" \
			-H "Content-Type: application/json" \
			--data "$body" "${MANAGER_URL}/runner/preempted" >/dev/null; then
			touch "$MARKER"
			logger -t gha-preempt-notify "reported ${reason} (preempted=${preempted}, runner_active=${runner_active}) to ${MANAGER_URL}"
			return 0
		fi
		sleep 2
	done
	logger -t gha-preempt-notify "failed to report ${reason} to ${MANAGER_URL} after ${attempt} attempts"
	return 1
}

case "$MODE" in
	watch)
		# Long-poll: the metadata server answers when the value changes or after timeout_sec.
		# Check the current value first (a flip during a gap is not missed), then long-poll.
		while true; do
			value=$(md "instance/preempted" 2>/dev/null || echo "")
			[ "$value" = "TRUE" ] && break
			md "instance/preempted?wait_for_change=true&timeout_sec=600" 620 >/dev/null 2>&1 || sleep 5
		done
		notify preempted
		;;
	shutdown)
		# Standard VMs are only ever shut down by the manager; report Spot VMs so a reclaim
		# that skipped the metadata flag is still visible (runner_active tells them apart).
		[ "$PREEMPTIBLE" = "TRUE" ] || exit 0
		notify shutdown
		;;
	*)
		echo "usage: $0 watch|shutdown" >&2
		exit 2
		;;
esac
NOTIFY
sudo chmod 0755 /usr/local/bin/gha-preempt-notify.sh

sudo tee /etc/systemd/system/gha-preempt-notify.service >/dev/null <<'UNIT'
[Unit]
Description=Report Spot preemption of this GitHub Actions runner VM to the manager
# Not ordered after google-startup-scripts.service: that oneshot unit runs the runner itself and
# only exits when the job is finished, so anything After= it would never run during a job.
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/gha-preempt-notify.sh watch
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

sudo tee /etc/systemd/system/gha-preempt-notify-shutdown.service >/dev/null <<'UNIT'
[Unit]
Description=Report shutdown of this GitHub Actions runner VM to the manager
# Stopped (ExecStop) before the network goes away at shutdown. Not ordered after
# google-startup-scripts.service (see gha-preempt-notify.service).
After=network-online.target
Wants=network-online.target
Before=shutdown.target
Conflicts=shutdown.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/true
ExecStop=/usr/local/bin/gha-preempt-notify.sh shutdown
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable gha-preempt-notify.service gha-preempt-notify-shutdown.service

# Cleanup: Clear package cache and temporary files
echo "Cleaning up..."
sudo apt-get clean
sudo rm -rf /tmp/* /root/.cache

# Cleanup: Rotate and vacuum journal logs
sudo journalctl --rotate
sudo journalctl --vacuum-time=1s

# Cleanup: Remove compressed and rotated log files, then truncate remaining logs
sudo find /var/log -type f \( -name "*.gz" -o -regex ".*\.[0-9]$" \) -delete
sudo find /var/log -type f -exec truncate -s 0 {} +

echo "Setup completed successfully"

# Shutdown VM
sudo shutdown -h now
