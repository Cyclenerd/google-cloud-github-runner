import pytest
import logging
from unittest.mock import Mock, patch
from app.services.webhook_service import WebhookService


class TestWebhookService:
    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_queued_job_with_matching_label(self, mock_gh_client_class, mock_gc_client_class):
        """Test handling queued job with matching label."""
        mock_gh_client = Mock()
        mock_gh_client.get_registration_token.return_value = "fake-token"
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
        mock_gc_client.create_runner_instance.return_value = "runner-abc123"
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        payload = {
            'action': 'queued',
            'workflow_job': {
                'labels': ['gcp-ubuntu-24.04', 'linux']
            },
            'repository': {
                'html_url': 'https://github.com/owner/repo',
                'full_name': 'owner/repo'
            }
        }

        result = service.handle_workflow_job(payload, delivery_id="delivery-001")

        assert result == {"action": "created", "runner_name": "runner-abc123"}
        mock_gh_client.get_registration_token.assert_called_once_with(
            repo_name='owner/repo', delivery_id="delivery-001"
        )
        mock_gc_client.create_runner_instance.assert_called_once_with(
            'fake-token',
            'https://github.com/owner/repo',
            'gcp-ubuntu-24.04',
            'owner/repo',
            delivery_id="delivery-001",
        )

    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_queued_job_for_org(self, mock_gh_client_class, mock_gc_client_class):
        """Test handling queued job for organization."""
        mock_gh_client = Mock()
        mock_gh_client.get_registration_token.return_value = "org-token"
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
        mock_gc_client.create_runner_instance.return_value = "runner-org456"
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        payload = {
            'action': 'queued',
            'workflow_job': {
                'labels': ['gcp-ubuntu-24.04']
            },
            'organization': {
                'login': 'my-org'
            },
            'repository': {
                'html_url': 'https://github.com/my-org/repo',
                'full_name': 'my-org/repo'
            }
        }

        result = service.handle_workflow_job(payload, delivery_id="delivery-org-001")

        assert result == {"action": "created", "runner_name": "runner-org456"}
        mock_gh_client.get_registration_token.assert_called_once_with(
            org_name='my-org', delivery_id="delivery-org-001"
        )

    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_queued_job_without_matching_label(self, mock_gh_client_class, mock_gc_client_class):
        """Test handling queued job without matching label."""
        mock_gh_client = Mock()
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        payload = {
            'action': 'queued',
            'workflow_job': {
                'labels': ['ubuntu-latest']
            },
            'repository': {
                'html_url': 'https://github.com/owner/repo',
                'full_name': 'owner/repo'
            }
        }

        result = service.handle_workflow_job(
            payload, delivery_id="delivery-nomatch-001"
        )

        assert result == {"action": "ignored", "runner_name": None}
        mock_gh_client.get_registration_token.assert_not_called()
        mock_gc_client.create_runner_instance.assert_not_called()

    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_completed_job(self, mock_gh_client_class, mock_gc_client_class):
        """Test handling completed job."""
        mock_gh_client = Mock()
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        payload = {
            'action': 'completed',
            'workflow_job': {
                'runner_name': 'runner-12345'
            }
        }

        result = service.handle_workflow_job(
            payload, delivery_id="delivery-completed-001"
        )

        assert result == {"action": "deleted", "runner_name": "runner-12345"}
        mock_gc_client.delete_runner_instance.assert_called_once_with(
            'runner-12345', delivery_id="delivery-completed-001"
        )

    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_completed_job_no_runner_name(self, mock_gh_client_class, mock_gc_client_class):
        """Test handling completed job without runner name."""
        mock_gh_client = Mock()
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        payload = {
            'action': 'completed',
            'workflow_job': {}
        }

        result = service.handle_workflow_job(
            payload, delivery_id="delivery-norunner-001"
        )

        assert result == {"action": "deleted", "runner_name": None}
        mock_gc_client.delete_runner_instance.assert_not_called()

    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_queued_job_raises_exception(self, mock_gh_client_class, mock_gc_client_class):
        """Test error handling when spawning runner fails."""
        mock_gh_client = Mock()
        mock_gh_client.get_registration_token.side_effect = Exception("API Error")
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        payload = {
            'action': 'queued',
            'workflow_job': {
                'labels': ['gcp-ubuntu-24.04']
            },
            'repository': {
                'html_url': 'https://github.com/owner/repo',
                'full_name': 'owner/repo'
            }
        }

        with pytest.raises(Exception, match="API Error"):
            service.handle_workflow_job(payload, delivery_id="delivery-error-001")

    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_queued_job_no_repo_or_org(self, mock_gh_client_class, mock_gc_client_class):
        """Test handling queued job when neither repo nor org is found."""
        mock_gh_client = Mock()
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        payload = {
            'action': 'queued',
            'workflow_job': {
                'labels': ['gcp-ubuntu-24.04']
            }
        }

        result = service.handle_workflow_job(payload, delivery_id="delivery-norepo-001")

        assert result == {"action": "created", "runner_name": None}
        mock_gh_client.get_registration_token.assert_not_called()
        mock_gc_client.create_runner_instance.assert_not_called()

    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_completed_job_with_error(self, mock_gh_client_class, mock_gc_client_class):
        """Test error handling when deleting runner fails."""
        mock_gh_client = Mock()
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
        mock_gc_client.delete_runner_instance.side_effect = Exception("Delete Error")
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        payload = {
            'action': 'completed',
            'workflow_job': {
                'runner_name': 'runner-12345'
            }
        }

        # Should not raise exception, just log error and return runner_name
        result = service.handle_workflow_job(payload, delivery_id="delivery-delerr-001")

        assert result == {"action": "deleted", "runner_name": "runner-12345"}
        mock_gc_client.delete_runner_instance.assert_called_once_with(
            'runner-12345', delivery_id="delivery-delerr-001"
        )


class TestWebhookServiceDeliveryIdLogging:
    """Tests to verify that delivery_id is logged throughout the webhook service."""

    @patch("app.services.webhook_service.GCloudClient")
    @patch("app.services.webhook_service.GitHubClient")
    def test_delivery_id_logged_on_queued_job(
        self, mock_gh_client_class, mock_gc_client_class, caplog
    ):
        """Test that delivery_id appears in logs when processing a queued job."""
        mock_gh_client = Mock()
        mock_gh_client.get_registration_token.return_value = "fake-token"
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
        mock_gc_client.create_runner_instance.return_value = "runner-abc123"
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        payload = {
            "action": "queued",
            "workflow_job": {"labels": ["gcp-ubuntu-24.04"]},
            "repository": {
                "html_url": "https://github.com/owner/repo",
                "full_name": "owner/repo",
            },
        }

        with caplog.at_level(logging.INFO, logger="app.services.webhook_service"):
            service.handle_workflow_job(payload, delivery_id="queued-delivery-123")

        delivery_logs = [
            r for r in caplog.records if "queued-delivery-123" in r.message
        ]
        assert (
            len(delivery_logs) >= 2
        ), "Expected delivery_id in at least 2 log lines (processing + label match)"

    @patch("app.services.webhook_service.GCloudClient")
    @patch("app.services.webhook_service.GitHubClient")
    def test_delivery_id_logged_on_completed_job(
        self, mock_gh_client_class, mock_gc_client_class, caplog
    ):
        """Test that delivery_id appears in logs when processing a completed job."""
        mock_gh_client = Mock()
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        payload = {
            "action": "completed",
            "workflow_job": {"runner_name": "runner-12345"},
        }

        with caplog.at_level(logging.INFO, logger="app.services.webhook_service"):
            service.handle_workflow_job(payload, delivery_id="completed-delivery-456")

        delivery_logs = [
            r for r in caplog.records if "completed-delivery-456" in r.message
        ]
        assert (
            len(delivery_logs) >= 2
        ), "Expected delivery_id in at least 2 log lines (processing + cleanup)"

    @patch("app.services.webhook_service.GCloudClient")
    @patch("app.services.webhook_service.GitHubClient")
    def test_delivery_id_logged_on_no_matching_label(
        self, mock_gh_client_class, mock_gc_client_class, caplog
    ):
        """Test that delivery_id appears in warning log when no matching label."""
        mock_gh_client_class.return_value = Mock()
        mock_gc_client_class.return_value = Mock()

        service = WebhookService()

        payload = {
            "action": "queued",
            "workflow_job": {"labels": ["ubuntu-latest"]},
            "repository": {
                "html_url": "https://github.com/owner/repo",
                "full_name": "owner/repo",
            },
        }

        with caplog.at_level(logging.WARNING, logger="app.services.webhook_service"):
            service.handle_workflow_job(payload, delivery_id="nomatch-delivery-789")

        assert any(
            "nomatch-delivery-789" in r.message for r in caplog.records
        ), "delivery_id not found in warning log for non-matching labels"

    @patch("app.services.webhook_service.GCloudClient")
    @patch("app.services.webhook_service.GitHubClient")
    def test_delivery_id_logged_on_spawn_error(
        self, mock_gh_client_class, mock_gc_client_class, caplog
    ):
        """Test that delivery_id appears in error log when spawning fails."""
        mock_gh_client = Mock()
        mock_gh_client.get_registration_token.side_effect = Exception("API Error")
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client_class.return_value = Mock()

        service = WebhookService()

        payload = {
            "action": "queued",
            "workflow_job": {"labels": ["gcp-ubuntu-24.04"]},
            "repository": {
                "html_url": "https://github.com/owner/repo",
                "full_name": "owner/repo",
            },
        }

        with caplog.at_level(logging.ERROR, logger="app.services.webhook_service"):
            with pytest.raises(Exception, match="API Error"):
                service.handle_workflow_job(payload, delivery_id="error-delivery-999")

        assert any(
            "error-delivery-999" in r.message for r in caplog.records
        ), "delivery_id not found in error log on spawn failure"

    @patch("app.services.webhook_service.GCloudClient")
    @patch("app.services.webhook_service.GitHubClient")
    def test_delivery_id_forwarded_to_gcloud_client(
        self, mock_gh_client_class, mock_gc_client_class
    ):
        """Test that delivery_id is forwarded to gcloud client on create and delete."""
        mock_gh_client = Mock()
        mock_gh_client.get_registration_token.return_value = "fake-token"
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
        mock_gc_client.create_runner_instance.return_value = "runner-fwd-123"
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        # Test create path
        payload = {
            "action": "queued",
            "workflow_job": {"labels": ["gcp-ubuntu-24.04"]},
            "repository": {
                "html_url": "https://github.com/owner/repo",
                "full_name": "owner/repo",
            },
        }
        service.handle_workflow_job(payload, delivery_id="fwd-create-001")
        mock_gc_client.create_runner_instance.assert_called_once_with(
            "fake-token",
            "https://github.com/owner/repo",
            "gcp-ubuntu-24.04",
            "owner/repo",
            delivery_id="fwd-create-001",
        )

    @patch("app.services.webhook_service.GCloudClient")
    @patch("app.services.webhook_service.GitHubClient")
    def test_delivery_id_forwarded_to_github_client(
        self, mock_gh_client_class, mock_gc_client_class
    ):
        """Test that delivery_id is forwarded to github client on token request."""
        mock_gh_client = Mock()
        mock_gh_client.get_registration_token.return_value = "fake-token"
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
        mock_gc_client.create_runner_instance.return_value = "runner-fwd-456"
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        payload = {
            "action": "queued",
            "workflow_job": {"labels": ["gcp-ubuntu-24.04"]},
            "repository": {
                "html_url": "https://github.com/owner/repo",
                "full_name": "owner/repo",
            },
        }
        service.handle_workflow_job(payload, delivery_id="fwd-gh-001")
        mock_gh_client.get_registration_token.assert_called_once_with(
            repo_name="owner/repo", delivery_id="fwd-gh-001"
        )
