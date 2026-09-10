"""
Routes called by the runner VMs themselves (authenticated with the VM service account's OIDC token).
"""
import logging
import os
from flask import Blueprint, request, jsonify
from app.clients import GCloudClient
from app.utils.security import verify_google_oidc_token
from app import limiter

logger = logging.getLogger(__name__)

runner_bp = Blueprint('runner', __name__, url_prefix='/runner')


def classify_preemption_report(body):
    """
    Decide what a VM's report means.

    Returns:
        tuple(bool, str): (record it as a preemption, human readable reason).
    """
    reason = str(body.get('reason') or 'unknown').lower()
    preempted = str(body.get('preempted') or '').upper() == 'TRUE'
    runner_active = body.get('runner_active') in (True, 'true', 'True', 'TRUE')
    if reason == 'preempted' or preempted:
        return True, 'preempted'
    if reason == 'shutdown' and runner_active:
        # The metadata flag was not seen but the runner was still working: treat as a reclaim.
        return True, 'shutdown-while-running'
    return False, reason


@runner_bp.route('/preempted', methods=['POST'])
@limiter.exempt
def preempted():
    """A runner VM reports that it is being preempted (or shut down while running a job)."""
    claims, why = verify_google_oidc_token(
        request.headers.get('Authorization'),
        os.environ.get('MANAGER_URL', '').strip().rstrip('/'),
        [os.environ.get('RUNNER_SERVICE_ACCOUNT_EMAIL', '')],
    )
    if claims is None:
        logger.error("Preemption report rejected: %s", why)
        status = 503 if 'not configured' in why else 403
        return jsonify({'status': 'forbidden', 'message': why}), status

    # The instance identity comes from the token (format=full), never from the body.
    compute_claims = (claims.get('google') or {}).get('compute_engine') or {}
    instance_name = compute_claims.get('instance_name')
    zone = compute_claims.get('zone')
    project_id = compute_claims.get('project_id')
    if not instance_name or not zone:
        logger.error("Preemption report rejected: token has no compute_engine claims (use format=full)")
        return jsonify({'status': 'forbidden', 'message': 'token has no compute_engine claims'}), 403
    expected_project = os.environ.get('GOOGLE_CLOUD_PROJECT')
    if expected_project and project_id and project_id != expected_project:
        logger.error("Preemption report rejected: instance %s belongs to project %s", instance_name, project_id)
        return jsonify({'status': 'forbidden', 'message': 'wrong project'}), 403

    body = request.get_json(silent=True) or {}
    record, reason = classify_preemption_report(body)
    job_id = body.get('job_id') or ''
    runner_name = body.get('runner_name') or instance_name
    if not record:
        logger.info(
            "Runner VM %s (zone %s, job %s) reported %s with runner_active=%s; not a preemption",
            instance_name, zone, job_id, reason, body.get('runner_active'),
        )
        return jsonify({'status': 'ignored', 'instance': instance_name, 'zone': zone, 'reason': reason}), 200

    logger.warning(
        "PREEMPTED runner VM %s in zone %s: runner %s, job %s, reason %s, preempted flag %s, runner_active %s",
        instance_name, zone, runner_name, job_id, reason, body.get('preempted'), body.get('runner_active'),
    )
    labelled = False
    try:
        labelled = GCloudClient().mark_instance_preempted(instance_name, zone, reason, delivery_id=f"preempt-{instance_name}")
    except Exception as e:
        # The report itself is the important part; the label is best effort.
        logger.error("Could not label instance %s in zone %s as preempted: %s", instance_name, zone, e)
    return jsonify({'status': 'recorded', 'instance': instance_name, 'zone': zone, 'job_id': job_id,
                    'reason': reason, 'labelled': labelled}), 200
