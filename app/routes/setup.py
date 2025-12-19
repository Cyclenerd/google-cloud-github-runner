"""
Routes for the GitHub App setup process.
"""
import logging
import os
import secrets
from flask import Blueprint, request, render_template, redirect, Response
from app.services import GitHubService, ConfigService

logger = logging.getLogger(__name__)

setup_bp = Blueprint('setup', __name__, url_prefix='/setup')


def check_auth(username, password):
    """Check if username/password combination is valid using timing-safe comparison."""
    expected_username = os.environ.get('SETUP_USERNAME', 'cloud')
    expected_password = os.environ.get('SETUP_PASSWORD') or os.environ.get('GOOGLE_CLOUD_PROJECT', '')

    # Use secrets.compare_digest for timing-safe comparison
    username_match = secrets.compare_digest(username, expected_username)
    password_match = secrets.compare_digest(password, expected_password)

    return username_match and password_match


def authenticate():
    """Send 401 response that enables basic auth."""
    return Response(
        'Authentication required',
        401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )


@setup_bp.before_request
def check_if_configured():
    """Check authentication and if GitHub App is already configured before processing setup requests."""
    # Check authentication first
    auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
        return authenticate()

    # Then check if configured
    config_service = ConfigService()
    config_status = config_service.is_configured()

    if config_status['is_configured']:
        logger.info("GitHub App already configured, redirecting to status page")
        return render_template('already_configured.html')


@setup_bp.route('/', methods=['GET'])
def setup():
    """Display GitHub App setup page with manifest."""
    base_url = request.url_root.rstrip('/').replace('http://', 'https://')
    # logger.info("Base URL: %s", base_url)

    manifest = GitHubService.generate_manifest(base_url)
    # logger.info("Manifest: %s", manifest)
    return render_template('setup.html', manifest=manifest)


@setup_bp.route('/callback', methods=['GET'])
def setup_callback():
    """Handle callback from GitHub after app creation."""
    config_service = ConfigService()
    code = request.args.get('code')
    if not code:
        return "Error: No code provided", 400

    try:
        config = GitHubService.exchange_code(code)

        app_id = config.get('id')
        pem = config.get('pem')
        webhook_secret = config.get('webhook_secret')
        app_slug = config.get('slug')

        try:
            config_service.store_github_app_id(app_id)
            config_service.store_github_private_key(pem)
            config_service.store_github_webhook_secret(webhook_secret)
            logger.info(f"Stored app configuration. App ID: {app_id}, awaiting installation...")
        except Exception as e:
            logger.error(f"Failed to store config: {e}")
            return "Error storing config", 507  # 507 Insufficient Storage

        # The app_slug is just the URL-friendly name of your GitHub App
        if app_slug:
            installation_url = GitHubService.get_installation_url(app_slug)
            logger.info(f"Redirecting to installation page: {installation_url}")
            return redirect(installation_url)
        else:
            return "Error: No GitHub app", 412  # 412 Precondition Failed

    except Exception as e:
        logger.error(f"Error exchanging code: {e}")
        return "Error exchanging code", 500


@setup_bp.route('/complete', methods=['GET'])
def setup_complete():
    """Handle redirect after GitHub App installation."""
    installation_id = request.args.get('installation_id')
    config_service = ConfigService()

    if installation_id:
        try:
            config_service.store_github_installation_id(installation_id)
            logger.info(f"Installation complete! Updated configuration with installation_id: {installation_id}")
            return render_template('success.html')
        except Exception as e:
            logger.error(f"Failed to update installation_id: {e}")
            return "Error updating installation_id", 500
    else:
        return "Error: No GitHub installation ID", 412  # 412 Precondition Failed


@setup_bp.route('/trigger-restart', methods=['POST'])
def trigger_restart():
    """Crash the application to force Cloud Run to restart the container and reload the environment variables."""
    logger.warning("Triggering application restart to reload environment variables...")

    # Use os._exit(1) to immediately terminate the process
    # This will cause Cloud Run to restart the container
    os._exit(1)
