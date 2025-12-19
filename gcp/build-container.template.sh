#!/usr/bin/env bash

# Helper script for Google Cloud Build
# Terraform managed!

#shellcheck disable=SC2154

set -e

# Check if required files exist
if [ ! -f "cloudbuild-container.yaml" ] || [ ! -f "../Dockerfile" ]; then
	echo "Error: This command must be executed in the gcp directory." >&2
	echo "Required files not found:"
	[ ! -f "cloudbuild-container.yaml" ] && echo "  - cloudbuild-container.yaml (in current directory)"
	[ ! -f "../Dockerfile" ] && echo "  - Dockerfile (in parent directory)"
	exit 1
fi

# Build the container image
echo "Building container image via Cloud Build..."
cd ..
gcloud builds submit --config "gcp/cloudbuild-container.yaml" --region="${region}" --gcs-source-staging-dir="gs://${bucket}/source" --project="${project_id}" --quiet
cd ~-

echo "✓ Container build completed successfully."
