import pytest
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

        service.handle_workflow_job(payload)

        mock_gh_client.get_registration_token.assert_called_once_with(repo_name='owner/repo')
        mock_gc_client.create_runner_instance.assert_called_once_with(
            'fake-token',
            'https://github.com/owner/repo',
            'gcp-ubuntu-24.04'
        )

    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_queued_job_for_org(self, mock_gh_client_class, mock_gc_client_class):
        """Test handling queued job for organization."""
        mock_gh_client = Mock()
        mock_gh_client.get_registration_token.return_value = "org-token"
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
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

        service.handle_workflow_job(payload)

        mock_gh_client.get_registration_token.assert_called_once_with(org_name='my-org')

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

        service.handle_workflow_job(payload)

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

        service.handle_workflow_job(payload)

        mock_gc_client.delete_runner_instance.assert_called_once_with('runner-12345')

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

        service.handle_workflow_job(payload)

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
            service.handle_workflow_job(payload)

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

        service.handle_workflow_job(payload)

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

        # Should not raise exception, just log error
        service.handle_workflow_job(payload)

        mock_gc_client.delete_runner_instance.assert_called_once_with('runner-12345')
