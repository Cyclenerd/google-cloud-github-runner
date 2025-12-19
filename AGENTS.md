# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## System Architecture

This document provides a high-level overview of the `google-cloud-github-runner` system, a self-hosted GitHub Actions Runners manager to start ephemeral Google Compute Engine (GCE) instances to run the CI jobs. It manages the lifecycle of these runners, ensuring they are registered with GitHub and deleted after use.

## Components

### 1. Flask Application (`app/`)
The core logic resides in a Flask web application.
- **Webhook Handler (`app/routes/webhook.py`)**: Receives `workflow_job` events from GitHub.
- **Webhook Service (`app/services/webhook_service.py.py`)**: Orchestrates the runner creation process.
- **GCloud Client (`app/clients/gcloud_client.py`)**: Interacts with Google Cloud APIs to create and delete instances.
- **GitHub Client (`app/clients/github_client.py`)**: Interacts with GitHub APIs to generate registration tokens and manage runners.

### 2. Google Cloud Infrastructure (`gcp/`)
The infrastructure is managed via Terraform.
- **Cloud Run**: Hosts the Python Flask application.
- **Compute Engine**: Runs the ephemeral GitHub runners.
- **Secret Manager**: Stores sensitive secrets (GitHub App private key, webhook secret).
- **Cloud Build**: Builds the Docker image for the Flask app.

## Workflows

### Runner Creation Flow
1. **Webhook**: GitHub sends a `workflow_job.queued` event to the Flask app.
2. **Validation**: The app validates the webhook signature and checks if the job labels match a supported runner template.
3. **Token Generation**: The app requests a runner registration token from GitHub.
4. **Instance Creation**: The app creates a GCE instance using a startup script that installs the GitHub runner agent and registers it with the token.

### Runner Cleanup Flow
- **Ephemeral Runners**: The runners are configured to be ephemeral (run once and terminate).
- **GCE Deletion**: GitHub sends a `workflow_job.completed` event to the Flask app. The GCE instance with the runner ID is deleted.

## Directory Structure

- `app/`: Python source code for the Flask application.
- `gcp/`: Terraform configuration for Google Cloud resources.
- `tests/`: Pytest test suite.
- `scripts/`: Utility scripts.

## Technologies Used

*   **Backend:** Python, Flask, Google Cloud SDK
*   **Frontend:** HTML, Jinja, JavaScript

## Python Coding Style

Follow these coding style rules when writing Python code:

*   **Linter:** Code must pass `flake8 --ignore=W292,W503 --max-line-length=127 --show-source --statistics *.py app/*.py app/routes/*.py app/services/*.py app/clients/*.py app/utils/*.py tests/*.py tests/integration/*.py tests/unit/*.py`
*   **Line Length:** Maximum line length is 127 characters
*   **Blank Lines:** No blank line should contain whitespace (trailing whitespace is not allowed)
*   **End of File:** W292 is ignored (no blank line required at end of file)
*   **Binary Operator:** W503 for line break before binary operator is ignored
*   **Spaces:** Indent with spaces

## Terraform Coding Style

Follow these coding style rules when writing Terraform code:

*   **Format:** Code must pass `terraform fmt -recursive -check -diff gcp`
*   **Linter:** Code must pass `tflint --chdir gcp`
*   **Security:** Code must pass `tfsec gcp`
*   **Spaces:** Indent with spaces

## Bash and Shell Script Coding Style

Follow these coding style rules when writing Terraform code:

*   **Linter:** Code must pass `shellcheck tools/*.sh && shellcheck gcp/*.sh && shellcheck gcp/startup/*.sh`
*   **Tabs:** Indent with tabs

## Testing

Follow these guidelines when working with tests:

*   **Test Framework:** Use pytest for all test cases
*   **Test Location:** Write test cases in the `tests/` directory
*   **Running Tests:** Always run tests after making changes using `python -m pytest tests/ -v`
*   **Test Coverage:** When adding new features or modifying existing code, write corresponding test cases
*   **Test Verification:** After writing test cases, run them to ensure they pass

Example commands:
```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_api.py -v

# Run tests with coverage
python -m pytest tests/ --cov
```
