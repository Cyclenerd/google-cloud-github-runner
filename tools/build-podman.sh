#!/usr/bin/env bash
set -e

# Define colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if Podman is installed
if ! command -v podman &> /dev/null; then
	echo "${RED}Error: Podman is not installed. Please install it to continue.${NC}" >&2
	exit 1
fi

# Check if required files exist
if [ ! -f "../Dockerfile" ]; then
	echo "${RED}Error: This command must be executed in the tools directory.${NC}" >&2
	echo "Required Dockerfile in parent directory not found."
	exit 1
fi

# Start Podman machine if not running
if ! podman machine list --format "{{.Running}}" | grep -q "true"; then
	echo -e "${YELLOW}Starting Podman machine...${NC}"
	podman machine start
fi

# Build the container image
echo -e "${YELLOW}Building container image with Podman...${NC}"
podman build \
	--platform "linux/amd64" \
	-f ../Dockerfile -t google-cloud-github-runner ../

echo -e "${GREEN}✓ Build script completed successfully.${NC}"
