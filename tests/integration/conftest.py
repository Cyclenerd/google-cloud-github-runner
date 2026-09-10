"""Integration test fixtures."""
import pytest
from app import create_app


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Set up test environment variables."""
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'test-project')
    monkeypatch.setenv('SETUP_USERNAME', 'setup-admin')
    monkeypatch.setenv('SETUP_PASSWORD', 'correct-horse-battery')


@pytest.fixture
def app():
    """Create test app for integration tests."""
    app = create_app()
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """Create test client for integration tests."""
    return app.test_client()
