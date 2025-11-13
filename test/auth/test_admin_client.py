"""
Tests for Admin OBP Client Singleton

Run with: pytest test/auth/test_admin_client.py -v
"""

import pytest
import os
from unittest.mock import AsyncMock, MagicMock, patch

from src.auth.admin_client import (
    AdminClientManager,
    initialize_admin_client,
    get_admin_client,
    get_admin_auth,
    close_admin_client,
    is_admin_client_initialized,
    _admin_manager
)


@pytest.fixture
def reset_singleton():
    """Reset the singleton between tests."""
    # Reset the singleton state
    _admin_manager._initialized = False
    _admin_manager._client = None
    _admin_manager._auth = None
    yield
    # Clean up after test
    _admin_manager._initialized = False
    _admin_manager._client = None
    _admin_manager._auth = None


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Mock required environment variables."""
    monkeypatch.setenv('OBP_ADMIN_USERNAME', 'test_admin')
    monkeypatch.setenv('OBP_ADMIN_PASSWORD', 'test_password')
    monkeypatch.setenv('OBP_CONSUMER_KEY', 'test_consumer_key')
    monkeypatch.setenv('OBP_BASE_URL', 'https://test.openbankproject.com')
    monkeypatch.setenv('OBP_API_VERSION', 'v6.0.0')


@pytest.mark.asyncio
async def test_singleton_pattern(reset_singleton):
    """Test that AdminClientManager follows singleton pattern."""
    manager1 = AdminClientManager()
    manager2 = AdminClientManager()
    
    assert manager1 is manager2, "Should return same instance"


@pytest.mark.asyncio
async def test_initialize_admin_client(reset_singleton, mock_env_vars):
    """Test admin client initialization."""
    
    with patch('src.auth.admin_client.create_admin_direct_login_auth') as mock_create_auth:
        # Mock the auth creation
        mock_auth = AsyncMock()
        mock_auth.acheck_auth = AsyncMock(return_value=True)
        mock_create_auth.return_value = mock_auth
        
        with patch('src.auth.admin_client.OBPClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            
            # Initialize
            await initialize_admin_client(verify_entitlements=False)
            
            # Verify it was initialized
            assert is_admin_client_initialized()
            assert get_admin_client() is mock_client
            assert get_admin_auth() is mock_auth


@pytest.mark.asyncio
async def test_get_client_before_init(reset_singleton):
    """Test that getting client before initialization raises error."""
    
    with pytest.raises(RuntimeError, match="not initialized"):
        get_admin_client()


@pytest.mark.asyncio
async def test_get_auth_before_init(reset_singleton):
    """Test that getting auth before initialization raises error."""
    
    with pytest.raises(RuntimeError, match="not initialized"):
        get_admin_auth()


@pytest.mark.asyncio
async def test_double_initialization(reset_singleton, mock_env_vars):
    """Test that double initialization is handled gracefully."""
    
    with patch('src.auth.admin_client.create_admin_direct_login_auth') as mock_create_auth:
        mock_auth = AsyncMock()
        mock_create_auth.return_value = mock_auth
        
        with patch('src.auth.admin_client.OBPClient'):
            # First initialization
            await initialize_admin_client(verify_entitlements=False)
            
            # Second initialization should skip
            await initialize_admin_client(verify_entitlements=False)
            
            # Should only be called once
            assert mock_create_auth.call_count == 1


@pytest.mark.asyncio
async def test_close_admin_client(reset_singleton, mock_env_vars):
    """Test cleanup of admin client."""
    
    with patch('src.auth.admin_client.create_admin_direct_login_auth') as mock_create_auth:
        mock_auth = AsyncMock()
        mock_session = AsyncMock()
        mock_auth.async_requests_client = mock_session
        mock_create_auth.return_value = mock_auth
        
        with patch('src.auth.admin_client.OBPClient'):
            # Initialize
            await initialize_admin_client(verify_entitlements=False)
            assert is_admin_client_initialized()
            
            # Close
            await close_admin_client()
            
            # Verify cleanup
            assert not is_admin_client_initialized()
            mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_initialization_failure(reset_singleton, mock_env_vars):
    """Test that initialization failures are handled properly."""
    
    with patch('src.auth.admin_client.create_admin_direct_login_auth') as mock_create_auth:
        # Mock a failure
        mock_create_auth.side_effect = ValueError("Invalid credentials")
        
        # Should raise ValueError
        with pytest.raises(ValueError, match="Admin client initialization failed"):
            await initialize_admin_client()
        
        # Should not be initialized
        assert not is_admin_client_initialized()


@pytest.mark.asyncio
async def test_missing_env_vars(reset_singleton, monkeypatch):
    """Test that missing environment variables are caught."""
    
    # Clear all admin env vars
    for var in ['OBP_ADMIN_USERNAME', 'OBP_ADMIN_PASSWORD', 'OBP_CONSUMER_KEY', 'OBP_BASE_URL']:
        monkeypatch.delenv(var, raising=False)
    
    with pytest.raises(ValueError, match="Admin client initialization failed"):
        await initialize_admin_client()


@pytest.mark.asyncio 
async def test_is_initialized_check(reset_singleton, mock_env_vars):
    """Test the is_initialized property."""
    
    assert not is_admin_client_initialized()
    
    with patch('src.auth.admin_client.create_admin_direct_login_auth') as mock_create_auth:
        mock_auth = AsyncMock()
        mock_create_auth.return_value = mock_auth
        
        with patch('src.auth.admin_client.OBPClient'):
            await initialize_admin_client(verify_entitlements=False)
            assert is_admin_client_initialized()
            
            await close_admin_client()
            assert not is_admin_client_initialized()
