import json
import logging
from unittest.mock import patch


class TestWebhookRoutes:
    @patch('app.routes.webhook.verify_github_signature')
    @patch('app.routes.webhook.WebhookService')
    def test_workflow_job_webhook(self, mock_webhook_service, mock_verify, client, sample_workflow_job_payload):
        """Test handling workflow_job webhook."""
        mock_verify.return_value = True
        mock_service_instance = mock_webhook_service.return_value
        mock_service_instance.handle_workflow_job.return_value = {
            "action": "created",
            "runner_name": "runner-abc123"
        }

        response = client.post(
            '/webhook',
            data=json.dumps(sample_workflow_job_payload),
            content_type='application/json',
            headers={
                'X-GitHub-Event': 'workflow_job',
                'X-GitHub-Delivery': 'abc-123-def'
            }
        )

        assert response.status_code == 200
        assert response.json['status'] == 'success'
        assert response.json['action'] == 'created'
        assert response.json['runner_name'] == 'runner-abc123'
        mock_service_instance.handle_workflow_job.assert_called_once_with(
            sample_workflow_job_payload, delivery_id="abc-123-def"
        )

    @patch('app.routes.webhook.verify_github_signature')
    @patch('app.routes.webhook.WebhookService')
    def test_workflow_job_webhook_created_response(self, mock_webhook_service, mock_verify, client):
        """Test that created runner name is included in the response body."""
        mock_verify.return_value = True
        mock_service_instance = mock_webhook_service.return_value
        mock_service_instance.handle_workflow_job.return_value = {
            "action": "created",
            "runner_name": "runner-uuid-12345"
        }

        payload = {
            'action': 'queued',
            'workflow_job': {'labels': ['gcp-ubuntu-24.04']},
            'repository': {
                'html_url': 'https://github.com/owner/repo',
                'full_name': 'owner/repo'
            }
        }

        response = client.post(
            '/webhook',
            data=json.dumps(payload),
            content_type='application/json',
            headers={
                'X-GitHub-Event': 'workflow_job',
                'X-GitHub-Delivery': 'delivery-created-001'
            }
        )

        assert response.status_code == 200
        assert response.json['status'] == 'success'
        assert response.json['action'] == 'created'
        assert response.json['runner_name'] == 'runner-uuid-12345'

    @patch('app.routes.webhook.verify_github_signature')
    @patch('app.routes.webhook.WebhookService')
    def test_workflow_job_webhook_deleted_response(self, mock_webhook_service, mock_verify, client):
        """Test that deleted runner name is included in the response body."""
        mock_verify.return_value = True
        mock_service_instance = mock_webhook_service.return_value
        mock_service_instance.handle_workflow_job.return_value = {
            "action": "deleted",
            "runner_name": "runner-12345"
        }

        payload = {
            'action': 'completed',
            'workflow_job': {'runner_name': 'runner-12345'}
        }

        response = client.post(
            '/webhook',
            data=json.dumps(payload),
            content_type='application/json',
            headers={
                'X-GitHub-Event': 'workflow_job',
                'X-GitHub-Delivery': 'delivery-deleted-001'
            }
        )

        assert response.status_code == 200
        assert response.json['status'] == 'success'
        assert response.json['action'] == 'deleted'
        assert response.json['runner_name'] == 'runner-12345'

    @patch('app.routes.webhook.verify_github_signature')
    @patch('app.routes.webhook.WebhookService')
    def test_workflow_job_webhook_ignored_response(self, mock_webhook_service, mock_verify, client):
        """Test that ignored jobs return null runner_name in response body."""
        mock_verify.return_value = True
        mock_service_instance = mock_webhook_service.return_value
        mock_service_instance.handle_workflow_job.return_value = {
            "action": "ignored",
            "runner_name": None
        }

        payload = {
            'action': 'queued',
            'workflow_job': {'labels': ['ubuntu-latest']},
            'repository': {
                'html_url': 'https://github.com/owner/repo',
                'full_name': 'owner/repo'
            }
        }

        response = client.post(
            '/webhook',
            data=json.dumps(payload),
            content_type='application/json',
            headers={
                'X-GitHub-Event': 'workflow_job',
                'X-GitHub-Delivery': 'delivery-ignored-001'
            }
        )

        assert response.status_code == 200
        assert response.json['status'] == 'success'
        assert response.json['action'] == 'ignored'
        assert response.json['runner_name'] is None

    @patch('app.routes.webhook.verify_github_signature')
    def test_installation_webhook(self, mock_verify, client, sample_installation_payload):
        """Test handling installation webhook."""
        mock_verify.return_value = True

        response = client.post(
            '/webhook',
            data=json.dumps(sample_installation_payload),
            content_type='application/json',
            headers={
                'X-GitHub-Event': 'installation',
                'X-GitHub-Delivery': 'delivery-install-001'
            }
        )

        assert response.status_code == 200
        assert response.json['status'] == 'ignored'

    @patch('app.routes.webhook.verify_github_signature')
    def test_unknown_webhook_event(self, mock_verify, client):
        """Test handling unknown webhook event."""
        mock_verify.return_value = True
        payload = {'action': 'test'}

        response = client.post(
            '/webhook',
            data=json.dumps(payload),
            content_type='application/json',
            headers={
                'X-GitHub-Event': 'unknown_event',
                'X-GitHub-Delivery': 'delivery-unknown-001'
            }
        )

        assert response.status_code == 200
        assert response.json['status'] == 'ignored'

    @patch('app.routes.webhook.verify_github_signature')
    @patch('app.routes.webhook.WebhookService')
    def test_workflow_job_webhook_error(self, mock_webhook_service, mock_verify, client, sample_workflow_job_payload):
        """Test error handling in workflow_job webhook."""
        mock_verify.return_value = True
        mock_service_instance = mock_webhook_service.return_value
        mock_service_instance.handle_workflow_job.side_effect = Exception("Processing error")

        response = client.post(
            '/webhook',
            data=json.dumps(sample_workflow_job_payload),
            content_type='application/json',
            headers={
                'X-GitHub-Event': 'workflow_job',
                'X-GitHub-Delivery': 'delivery-error-001'
            }
        )

        assert response.status_code == 500
        assert response.json['status'] == 'error'
        # Security improvement: we now return generic 'Internal error' instead of exposing the actual error
        assert response.json['message'] == 'Internal error'

    @patch('app.routes.webhook.verify_github_signature')
    def test_webhook_invalid_signature(self, mock_verify, client):
        """Test webhook with invalid signature."""
        mock_verify.return_value = False

        response = client.post(
            '/webhook',
            data=json.dumps({'test': 'data'}),
            content_type='application/json',
            headers={
                'X-GitHub-Event': 'workflow_job',
                'X-Hub-Signature-256': 'invalid',
                'X-GitHub-Delivery': 'delivery-sig-001'
            }
        )

        assert response.status_code == 403
        assert response.json['status'] == 'forbidden'

    def test_webhook_ping_event(self, client):
        """Test webhook ping event."""
        response = client.post(
            '/webhook',
            data=json.dumps({'zen': 'test'}),
            content_type='application/json',
            headers={
                'X-GitHub-Event': 'ping',
                'X-GitHub-Delivery': 'delivery-ping-001'
            }
        )

        assert response.status_code == 200
        assert response.json['status'] == 'success'


class TestWebhookDeliveryIdLogging:
    """Tests to verify that X-GitHub-Delivery header is logged for correlation."""

    @patch('app.routes.webhook.verify_github_signature')
    @patch('app.routes.webhook.WebhookService')
    def test_delivery_id_logged_on_workflow_job(
        self, mock_webhook_service, mock_verify, client, caplog
    ):
        """Test that delivery_id is logged when processing a workflow_job event."""
        mock_verify.return_value = True
        mock_service_instance = mock_webhook_service.return_value
        mock_service_instance.handle_workflow_job.return_value = {
            "action": "created",
            "runner_name": "runner-abc123"
        }

        payload = {
            'action': 'queued',
            'workflow_job': {'labels': ['gcp-ubuntu-24.04']},
            'repository': {
                'html_url': 'https://github.com/owner/repo',
                'full_name': 'owner/repo'
            }
        }

        with caplog.at_level(logging.INFO, logger='app.routes.webhook'):
            client.post(
                '/webhook',
                data=json.dumps(payload),
                content_type='application/json',
                headers={
                    'X-GitHub-Event': 'workflow_job',
                    'X-GitHub-Delivery': 'f47ac10b-58cc-4372-a567-0e02b2c3d479'
                }
            )

        assert any(
            'f47ac10b-58cc-4372-a567-0e02b2c3d479' in record.message
            for record in caplog.records
        ), "delivery_id was not found in log output"

    @patch('app.routes.webhook.verify_github_signature')
    def test_delivery_id_logged_on_unknown_event(self, mock_verify, client, caplog):
        """Test that delivery_id is logged for unknown event types."""
        mock_verify.return_value = True

        with caplog.at_level(logging.WARNING, logger='app.routes.webhook'):
            client.post(
                '/webhook',
                data=json.dumps({'action': 'test'}),
                content_type='application/json',
                headers={
                    'X-GitHub-Event': 'unknown_event',
                    'X-GitHub-Delivery': 'aaaabbbb-cccc-dddd-eeee-ffffffffffff'
                }
            )

        assert any(
            'aaaabbbb-cccc-dddd-eeee-ffffffffffff' in record.message
            for record in caplog.records
        ), "delivery_id was not found in log output for unknown event"

    @patch('app.routes.webhook.verify_github_signature')
    def test_delivery_id_logged_on_invalid_signature(self, mock_verify, client, caplog):
        """Test that delivery_id is logged when signature verification fails."""
        mock_verify.return_value = False

        with caplog.at_level(logging.ERROR, logger='app.routes.webhook'):
            client.post(
                '/webhook',
                data=json.dumps({'test': 'data'}),
                content_type='application/json',
                headers={
                    'X-GitHub-Event': 'workflow_job',
                    'X-Hub-Signature-256': 'invalid',
                    'X-GitHub-Delivery': '11112222-3333-4444-5555-666677778888'
                }
            )

        assert any(
            '11112222-3333-4444-5555-666677778888' in record.message
            for record in caplog.records
        ), "delivery_id was not found in log output for invalid signature"

    @patch('app.routes.webhook.verify_github_signature')
    @patch('app.routes.webhook.WebhookService')
    def test_delivery_id_logged_on_webhook_error(
        self, mock_webhook_service, mock_verify, client, caplog
    ):
        """Test that delivery_id is logged when webhook processing fails."""
        mock_verify.return_value = True
        mock_service_instance = mock_webhook_service.return_value
        mock_service_instance.handle_workflow_job.side_effect = Exception("boom")

        payload = {
            'action': 'queued',
            'workflow_job': {'labels': ['gcp-ubuntu-24.04']},
            'repository': {
                'html_url': 'https://github.com/owner/repo',
                'full_name': 'owner/repo'
            }
        }

        with caplog.at_level(logging.ERROR, logger='app.routes.webhook'):
            client.post(
                '/webhook',
                data=json.dumps(payload),
                content_type='application/json',
                headers={
                    'X-GitHub-Event': 'workflow_job',
                    'X-GitHub-Delivery': 'error-delivery-id-999'
                }
            )

        assert any(
            'error-delivery-id-999' in record.message
            for record in caplog.records
        ), "delivery_id was not found in error log output"

    @patch('app.routes.webhook.verify_github_signature')
    @patch('app.routes.webhook.WebhookService')
    def test_delivery_id_none_when_header_missing(
        self, mock_webhook_service, mock_verify, client, caplog
    ):
        """Test that delivery_id is logged as None when header is missing."""
        mock_verify.return_value = True
        mock_service_instance = mock_webhook_service.return_value
        mock_service_instance.handle_workflow_job.return_value = {
            "action": "created",
            "runner_name": "runner-no-delivery"
        }

        payload = {
            'action': 'queued',
            'workflow_job': {'labels': ['gcp-ubuntu-24.04']},
            'repository': {
                'html_url': 'https://github.com/owner/repo',
                'full_name': 'owner/repo'
            }
        }

        with caplog.at_level(logging.INFO, logger='app.routes.webhook'):
            response = client.post(
                '/webhook',
                data=json.dumps(payload),
                content_type='application/json',
                headers={'X-GitHub-Event': 'workflow_job'}
            )

        assert response.status_code == 200
        # delivery_id should be None in the log since header was not sent
        assert any(
            'delivery_id: None' in record.message
            for record in caplog.records
        ), "delivery_id: None was not found in log output when header is missing"
