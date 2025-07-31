import pytest
import os
from unittest.mock import Mock, patch
from pathlib import Path
import sys

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

# Set environment variables before importing modules
os.environ.setdefault('SESSION_SECRET_KEY', 'test-secret-key')
os.environ.setdefault('OBP_BASE_URL', 'https://test-api.example.com')
os.environ.setdefault('OBP_CONSUMER_KEY', 'test-consumer-key')

from auth.auth import BaseAuth, AuthConfig, OBPConsentAuth, OBPDirectLoginAuth
from auth.schema import DirectLoginConfig
from auth.usage_tracker import AnonymousUsageTracker
from auth.session import SessionData


class TestBaseAuth:
    def test_init(self):
        auth = BaseAuth()
        assert auth.async_requests_client is None

    def test_construct_headers_raises_not_implemented(self):
        auth = BaseAuth()
        with pytest.raises(NotImplementedError):
            auth.construct_headers()


class TestAuthConfig:
    def test_init_with_auth_types(self):
        mock_auth = Mock()
        config = AuthConfig({'consent': mock_auth})
        assert config.consent == mock_auth


class TestOBPConsentAuth:
    @patch.dict(os.environ, {'OBP_BASE_URL': 'https://test.com', 'OBP_CONSUMER_KEY': 'test-key'})
    def test_init(self):
        auth = OBPConsentAuth()
        assert auth.base_uri == 'https://test.com'
        assert auth.opey_consumer_key == 'test-key'

    @patch.dict(os.environ, {'OBP_BASE_URL': 'https://test.com', 'OBP_CONSUMER_KEY': 'test-key'})
    def test_construct_headers(self):
        auth = OBPConsentAuth()
        headers = auth.construct_headers("test-token")
        assert headers['Consent-JWT'] == "test-token"
        assert headers['Consumer-Key'] == "test-key"


class TestOBPDirectLoginAuth:
    def test_init_no_config(self):
        auth = OBPDirectLoginAuth()
        assert not hasattr(auth, 'username')

    def test_construct_headers(self):
        auth = OBPDirectLoginAuth()
        headers = auth.construct_headers("test-token")
        assert headers['Authorization'] == "DirectLogin token=test-token"


class TestDirectLoginConfig:
    def test_create_config(self):
        config = DirectLoginConfig(
            username="test",
            password="pass",
            consumer_key="key",
            base_uri="http://test.api"
        )
        assert config.username == "test"
        assert config.password == "pass"
        assert config.consumer_key == "key"
        assert config.base_uri == "http://test.api"


class TestUsageTracker:
    def test_init_defaults(self):
        tracker = AnonymousUsageTracker()
        assert tracker.anonymous_token_limit == 10000
        assert tracker.anonymous_request_limit == 20

    # def test_update_token_usage(self):
    #     tracker = AnonymousUsageTracker()
    #     session = SessionData(is_anonymous=True, token_usage=100)
    #     updated = tracker.update_token_usage(session, 50)
    #     assert updated.token_usage == 150


class TestSessionData:
    def test_defaults(self):
        session = SessionData()
        assert session.consent_jwt is None
        assert session.is_anonymous is False
        assert session.token_usage == 0
        assert session.request_count == 0
