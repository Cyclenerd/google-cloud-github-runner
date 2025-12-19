#!/usr/bin/env bash

# Copyright 2025 Nils Knieling. All Rights Reserved.
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

# Install Docker and GitHub Actions Runner for Linux with x64 or ARM64 CPU architecture
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

# Patch for Ubuntu 24.04 (https://github.com/actions/runner/issues/3150)
sudo sed -i 's/libicu72/libicu72 libicu74/' ./bin/installdependencies.sh

# Run the installation script
sudo ./bin/installdependencies.sh
echo "GitHub Actions Runner installed successfully"

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
