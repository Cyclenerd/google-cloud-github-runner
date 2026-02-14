#!/bin/bash
set -euo pipefail

# Assign Google Cloud IAM roles to a user at project level
# Usage: ./assign-iam-roles.sh <PROJECT_ID> <GOOGLE_ACCOUNT_EMAIL>

if [ "$#" -ne 2 ]; then
	echo "Usage: $0 <PROJECT_ID> <GOOGLE_ACCOUNT_EMAIL>"
	echo "Example: $0 my-project-id user@example.com"
	exit 1
fi

PROJECT_ID="$1"
GOOGLE_ACCOUNT_EMAIL="$2"

# Validate project ID format
if [[ ! "$PROJECT_ID" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]]; then
	echo "Error: Invalid project ID format: $PROJECT_ID"
	echo "Project ID must be 6-30 characters, start with a lowercase letter, and contain only lowercase letters, numbers, and hyphens"
	exit 1
fi

# Validate user email format
if [[ ! "$GOOGLE_ACCOUNT_EMAIL" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
	echo "Error: Invalid email format: $GOOGLE_ACCOUNT_EMAIL"
	exit 1
fi

MEMBER="user:$GOOGLE_ACCOUNT_EMAIL"

# Define roles to assign
ROLES=(
	"roles/artifactregistry.admin"
	"roles/cloudbuild.builds.editor"
	"roles/compute.admin"
	"roles/iam.roleViewer"
	"roles/iam.serviceAccountAdmin"
	"roles/iam.serviceAccountUser"
	"roles/logging.admin"
	"roles/monitoring.admin"
	"roles/orgpolicy.policyViewer"
	"roles/resourcemanager.projectIamAdmin"
	"roles/run.admin"
	"roles/secretmanager.admin"
	"roles/serviceusage.serviceUsageAdmin"
	"roles/storage.admin"
)

echo "Assigning IAM roles to $GOOGLE_ACCOUNT_EMAIL in project $PROJECT_ID..."
echo

for ROLE in "${ROLES[@]}"; do
	echo "Assigning role: $ROLE"
	if gcloud projects add-iam-policy-binding "$PROJECT_ID" \
		--member="$MEMBER" \
		--role="$ROLE" \
		--condition=None \
		--quiet > /dev/null 2>&1; then
		echo "✓ Successfully assigned $ROLE"
	else
		echo "✗ Failed to assign $ROLE"
	fi
done

echo
echo "IAM role assignment completed for $GOOGLE_ACCOUNT_EMAIL"
