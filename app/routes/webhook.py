"""
Routes for handling GitHub webhooks.
"""
import logging
from flask import Blueprint, request, jsonify
from app.services import WebhookService
from app.utils.security import verify_github_signature
from app import limiter

logger = logging.getLogger(__name__)

webhook_bp = Blueprint('webhook', __name__)


@webhook_bp.route('/webhook', methods=['POST'])
@limiter.limit("1000 per hour")  # Higher limit for high-traffic webhook endpoint
def webhook():
    """Handle incoming GitHub webhook events."""
    # https://docs.github.com/en/webhooks/webhook-events-and-payloads
    event_type = request.headers.get('X-GitHub-Event')

    # Validate event type
    if not event_type or not isinstance(event_type, str):
        logger.error("Missing or invalid X-GitHub-Event header")
        return jsonify({'status': 'error', 'message': 'Invalid event type'}), 400

    logger.info("Received webhook event: %s", event_type)

    # Handle ping event
    if event_type == 'ping':
        return jsonify({'status': 'success'}), 200

    # Verify GitHub signature
    signature = request.headers.get('X-Hub-Signature-256')

    if not verify_github_signature(request.data, signature):
        logger.error("GitHub webhook signature not successfully verified! Ignoring webhook event.")
        return jsonify({'status': 'forbidden', 'message': 'Invalid signature'}), 403

    # Validate JSON payload
    try:
        payload = request.json
        if not payload:
            logger.error("Empty or invalid JSON payload")
            return jsonify({'status': 'error', 'message': 'Invalid JSON payload'}), 400
    except Exception as e:
        logger.error("Failed to parse JSON payload: %s", str(e))
        return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400

    # https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_job
    if event_type == 'workflow_job':
        return handle_workflow_job_event(payload)
    else:
        logger.warning("Received unknown event type: %s", event_type)
        return jsonify({'status': 'ignored'}), 200


def handle_workflow_job_event(payload):
    """Handle workflow_job event."""
    try:
        webhook_service = WebhookService()
        webhook_service.handle_workflow_job(payload)
        return jsonify({'status': 'success'}), 200
    except ValueError as e:
        logger.error("[Webhook] Validation error: %s", str(e))
        return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400
    except Exception as e:
        logger.error("[Webhook] Error handling webhook: %s", str(e))
        return jsonify({'status': 'error', 'message': 'Internal error'}), 500
