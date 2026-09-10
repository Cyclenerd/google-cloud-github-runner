"""
Route called by Cloud Tasks (OIDC-authenticated) to provision the runner VM for one job.
"""
import logging
import os
from flask import Blueprint, request, jsonify
from app.clients.gcloud_client import InstanceCreationError, ZoneCapacityError
from app.utils.auto_label import InvalidAutoLabel
from app.services import WebhookService
from app.utils.security import verify_google_oidc_token
from app import limiter

logger = logging.getLogger(__name__)

tasks_bp = Blueprint('tasks', __name__, url_prefix='/tasks')


@tasks_bp.route('/provision', methods=['POST'])
@limiter.exempt
def provision():
    """Create the VM for the job in the task body. Non-2xx answers make Cloud Tasks retry."""
    claims, reason = verify_google_oidc_token(
        request.headers.get('Authorization'),
        os.environ.get('MANAGER_URL', '').strip().rstrip('/'),
        [os.environ.get('PROVISION_INVOKER_EMAIL', '')],
    )
    if claims is None:
        logger.error("Provisioning task rejected: %s", reason)
        status = 503 if 'not configured' in reason else 403
        return jsonify({'status': 'forbidden', 'message': reason}), status

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get('job_id') is None or not payload.get('template_name'):
        logger.error("Provisioning task rejected: invalid payload")
        return jsonify({'status': 'error', 'message': 'invalid payload'}), 400  # not retried

    task_name = request.headers.get('X-CloudTasks-TaskName', '')
    attempt = request.headers.get('X-CloudTasks-TaskRetryCount', '0')
    logger.info("Provisioning task %s attempt %s for job %s, delivery_id: %s",
                task_name, attempt, payload.get('job_id'), payload.get('delivery_id'))
    try:
        result = WebhookService().provision_from_task(payload)
    except (InvalidAutoLabel, ValueError) as e:
        # A malformed label or payload will not get better with retries; the reconciler reports it.
        logger.error("Provisioning task for job %s rejected: %s", payload.get('job_id'), e)
        return jsonify({'status': 'skipped', 'job_id': payload.get('job_id'), 'reason': str(e)}), 200
    except ZoneCapacityError as e:
        # No zone (or rung) had capacity right now: let the queue retry with backoff.
        logger.warning("Provisioning task for job %s: no capacity (%s); asking Cloud Tasks to retry",
                       payload.get('job_id'), e)
        return jsonify({'status': 'retry', 'message': 'no capacity'}), 503
    except InstanceCreationError as e:
        logger.error("Provisioning task for job %s failed: %s; asking Cloud Tasks to retry", payload.get('job_id'), e)
        return jsonify({'status': 'retry', 'message': 'creation failed'}), 500
    except Exception as e:
        logger.exception("Provisioning task for job %s failed: %s", payload.get('job_id'), e)
        return jsonify({'status': 'retry', 'message': 'internal error'}), 500
    return jsonify({'status': 'success', **result}), 200
