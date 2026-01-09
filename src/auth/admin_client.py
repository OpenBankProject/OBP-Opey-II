"""
Admin OBP Client Singleton

This module provides a singleton admin OBP client for administrative operations
across the application. The client is initialized during app startup and can be
accessed via get_admin_client().
"""

import logging
from typing import Optional

from client.obp_client import OBPClient
from .auth import create_admin_direct_login_auth, OBPDirectLoginAuth

logger = logging.getLogger('__main__.' + __name__)


class AdminClientManager:
    """
    Manages a singleton instance of the admin OBP client.
    
    This ensures that:
    1. Admin authentication is performed once at startup
    2. The same authenticated client is reused across the application
    3. Token refresh is handled centrally
    """
    
    _instance: Optional['AdminClientManager'] = None
    _client: Optional[OBPClient] = None
    _auth: Optional[OBPDirectLoginAuth] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def initialize(
        self,
        required_entitlements: Optional[list[str]] = None,
        verify_entitlements: bool = True
    ) -> None:
        """
        Initialize the admin client during app startup.
        
        Args:
            required_entitlements: List of required role names to verify
            verify_entitlements: Whether to verify admin entitlements
            
        Raises:
            ValueError: If initialization fails or credentials are invalid
        """
        if self._initialized:
            logger.warning('Admin client already initialized, skipping...')
            return
        
        try:
            logger.info('🔧 Initializing admin OBP client...')
            
            # Create admin authentication
            self._auth = await create_admin_direct_login_auth(
                required_entitlements=required_entitlements,
                verify_entitlements=verify_entitlements
            )
            
            # Create OBP client with admin auth
            self._client = OBPClient(auth=self._auth)
            
            self._initialized = True
            logger.info('✅ Admin OBP client initialized successfully')
            
        except Exception as e:
            logger.error(f'❌ Failed to initialize admin OBP client: {e}')
            raise ValueError(f'Admin client initialization failed: {e}') from e
    
    def get_client(self) -> OBPClient:
        """
        Get the singleton admin OBP client instance.
        
        Returns:
            OBPClient: The initialized admin OBP client
            
        Raises:
            RuntimeError: If the client hasn't been initialized
        """
        if not self._initialized or self._client is None:
            raise RuntimeError(
                'Admin client not initialized. Call initialize() during app startup.'
            )
        return self._client
    
    def get_auth(self) -> OBPDirectLoginAuth:
        """
        Get the admin authentication instance.
        
        Returns:
            OBPDirectLoginAuth: The admin authentication instance
            
        Raises:
            RuntimeError: If the client hasn't been initialized
        """
        if not self._initialized or self._auth is None:
            raise RuntimeError(
                'Admin client not initialized. Call initialize() during app startup.'
            )
        return self._auth
    
    @property
    def is_initialized(self) -> bool:
        """Check if the admin client is initialized."""
        return self._initialized
    
    async def close(self) -> None:
        """Clean up resources during app shutdown."""
        if self._auth and hasattr(self._auth, 'async_requests_client'):
            if self._auth.async_requests_client:
                await self._auth.async_requests_client.close()
                logger.info('🔌 Admin client HTTP session closed')
        
        self._initialized = False
        self._client = None
        self._auth = None
        logger.info('👋 Admin client cleaned up')


# Singleton instance
_admin_manager = AdminClientManager()


async def initialize_admin_client(
    required_entitlements: Optional[list[str]] = None,
    verify_entitlements: bool = True
) -> None:
    """
    Initialize the admin OBP client. Call this during app startup.
    
    Args:
        required_entitlements: List of required role names to verify
        verify_entitlements: Whether to verify admin entitlements
    """
    await _admin_manager.initialize(
        required_entitlements=required_entitlements,
        verify_entitlements=verify_entitlements
    )


def get_admin_client() -> OBPClient:
    """
    Get the singleton admin OBP client.
    
    Returns:
        OBPClient: The initialized admin OBP client
        
    Raises:
        RuntimeError: If initialize_admin_client() hasn't been called
        
    Example:
        >>> # During app startup
        >>> await initialize_admin_client()
        >>> 
        >>> # Later, anywhere in the app
        >>> admin_client = get_admin_client()
        >>> response = await admin_client.get("/obp/v6.0.0/banks")
    """
    return _admin_manager.get_client()


def get_admin_auth() -> OBPDirectLoginAuth:
    """
    Get the admin authentication instance.
    
    Returns:
        OBPDirectLoginAuth: The admin authentication instance
        
    Raises:
        RuntimeError: If initialize_admin_client() hasn't been called
    """
    return _admin_manager.get_auth()


async def close_admin_client() -> None:
    """
    Close the admin client and clean up resources.
    Call this during app shutdown.
    """
    await _admin_manager.close()


def is_admin_client_initialized() -> bool:
    """Check if the admin client is initialized."""
    return _admin_manager.is_initialized
