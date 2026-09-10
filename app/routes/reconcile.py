"""
Route for the periodic reconciler (invoked by Cloud Scheduler with an OIDC token).
"""
import logging
import os
import threading
from flask import Blueprint, request, jsonify
from app.services import ReconcileService
from app.utils.security import verify_google_oidc_token
from app import limiter

logger = logging.getLogger(__name__)

reconcile_bp = Blueprint('reconcile', __name__)

# One pass per process at a time; overlapping passes would only race each other.
_reconcile_lock = threading.Lock()


@reconcile_bp.route('/reconcile', methods=['POST'])
@limiter.exempt
def reconcile():
    """Run one reconciliation pass. Query ``dry_run=1`` reports decisions without acting."""
    claims, reason = verify_google_oidc_token(
        request.headers.get('Authorization'),
        os.environ.get('RECONCILE_AUDIENCE'),
        [os.environ.get('RECONCILE_INVOKER_EMAIL', '')],
    )
    if claims is None:
        logger.error("Reconcile request rejected: %s", reason)
        status = 503 if 'not configured' in reason else 403
        return jsonify({'status': 'forbidden', 'message': reason}), status

    dry_run = request.args.get('dry_run', '').lower() in ('1', 'true', 'yes')
    if not _reconcile_lock.acquire(blocking=False):
        logger.warning("Reconcile request skipped: a pass is already running in this instance")
        return jsonify({'status': 'busy', 'message': 'a reconcile pass is already running'}), 409
    try:
        report = ReconcileService().run(dry_run=dry_run)
        return jsonify({'status': 'success', **report}), 200
    except Exception as e:
        logger.exception("Reconcile pass failed: %s", e)
        return jsonify({'status': 'error', 'message': 'reconcile pass failed'}), 500
    finally:
        _reconcile_lock.release()
