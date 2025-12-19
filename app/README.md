# Application Source Code

This directory contains the core source code for the Python GitHub Actions Runners Manager application.

## Structure

*   **`routes/`**: Flask route definitions handling HTTP requests (webhooks, setup pages).
*   **`services/`**: Core business logic (runner management, GitHub app configuration, webhook processing).
*   **`clients/`**: Wrappers for external APIs (Google Cloud, GitHub).
*   **`templates/`**: Jinja2 HTML templates for the web interface.
*   **`static/`**: Static assets (CSS, images, JavaScript).
*   **`utils/`**: Helper functions and utilities.

## Key Components

*   **Webhook Handler**: Processes `workflow_job` events from GitHub to trigger runner creation or deletion.
*   **GCloud Client**: Manages Google Compute Engine instances (creation, deletion) and Secret Manager interactions.
*   **Config Service**: Handles application configuration and secure retrieval of secrets.
