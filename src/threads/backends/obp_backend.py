import logging

from abc import ABC, abstractmethod
from typing import List, Dict
from uuid import UUID
from ..model import Thread
from .backend import ThreadBackend
from client.obp_client import OBPClient

logger = logging.getLogger(__name__)

# Probably no good reason to change this, but keeping it configurable for future-proofing
OPEY_THREAD_ENTITY_NAME = "OpeyThread"
OPEY_THREAD_ENTITY_DESCRIPTION = "Dynamic entity to store Opey AI threads"

def initialize_obp_thread_backend(obp_client: OBPClient) -> None:
    """
    Initialize the OBP thread backend on OBP using dynamic entities.
    
    """
    if not _check_for_entitlements(obp_client):
        raise PermissionError("Missing required entitlements to initialize OBP thread backend.")
    
    if _check_for_existing_obp_thread_backend(obp_client):
        logger.info("OBP thread backend already initialized, skipping initialization.")
        return
    
    
    # Define the dynamic entity for threads
    thread_entity_definition = {
        "bankId": "",
        OPEY_THREAD_ENTITY_NAME: {
            "description": OPEY_THREAD_ENTITY_DESCRIPTION,
            "required": {
                "thread_id",
                "title",
                "created_at",
                "updated_at",
            },
            "properties": {
                "thread_id":
                    {
                        "type": "string",
                        "example": "123e4567-e89b-12d3-a456-426614174000",
                        "description": "UUID Unique identifier for the thread",
                    },
                "title":
                    {
                        "type": "string",
                        "example": "My First Thread",
                        "description": "Title of the thread",
                    },
                "created_at":
                    {
                        "type": "string",
                        "example": "2024-01-01T12:00:00Z",
                        "description": "ISO Timestamp when the thread was created",
                    },
                "updated_at":
                    {
                        "type": "string",
                        "example": "2024-01-02T12:00:00Z",
                        "description": "ISO Timestamp when the thread was last updated",
                    },
            }
        }
    }
    
    
    
    
    pass

def _check_for_entitlements(obp_client: OBPClient) -> bool:
    """
    Check if the OBP client and user has the necessary entitlements to manage threads.
    
    Returns:
        bool: True if entitlements are present, False otherwise.
        
    """
    try:
        response = obp_client.sync_obp_requests("GET", "/obp/v5.1.0/my/entitlements", "", as_json=True)
    except Exception as e:
        logger.error(f"Error checking entitlements: {e}")
        return False
    
    if not response:
        return False
    
    if not isinstance(response, Dict):
        logger.error(f"Unexpected response format when checking entitlements: {response}")
        return False
    
    entitlements = response.get("entitlements", [])
    
    required_entitlements = {"CanCreateSystemLevelDynamicEntity", "CanGetSystemLevelDynamicEntities"}
    
    for entitlement in entitlements:
        if entitlement.get("role_name") in required_entitlements:
            required_entitlements.remove(entitlement.get("name"))
    
    if required_entitlements:
        logger.warning(f"Missing required entitlements: {required_entitlements}")
        return False
    
    return True

def _check_for_existing_obp_thread_backend(obp_client: OBPClient) -> bool:
    """
    Check if the OBP thread backend is already initialized on OBP.
    
    Returns:
        bool: True if initialized, False otherwise.
        
    """

    # Get all dynamic entities from OBP
    try:
        response = obp_client.sync_obp_requests("GET", "/obp/v5.1.0/management/system-dynamic-entities", "", as_json=True)
    except Exception as e:
        logger.error(f"Error checking for existing OBP thread backend: {e}")
        return False
    
    if not response:
        return False
    
    if not isinstance(response, Dict):
        logger.error(f"Unexpected response format when checking for existing OBP thread backend: {response}")
        return False
    
    existing_entities = response.get("dynamic_entities", [])
    
    # Check if an entity for threads already exists
    for entity in existing_entities:
        if OPEY_THREAD_ENTITY_NAME in entity:
            logger.info("OBP thread backend already initialized.")
            return True
        
    return False
    
    

class OBPThreadBackend(ThreadBackend):
    def __init__(self, obp_client: OBPClient):
        self.obp_client = obp_client

    async def create(self, thread: Thread) -> None:
        """Persist a new thread to OBP API."""
        # TODO: Implement OBP API endpoint for thread creation
        await self.obp_client.async_obp_requests(
            method="POST",
            path="/obp/v5.1.0/management/ai-threads",
            body=thread.model_dump_json()
        )

    async def read(self, thread_id: UUID) -> Thread:
        """Retrieve a thread from OBP API."""
        # TODO: Implement OBP API endpoint for thread retrieval
        response = await self.obp_client.async_obp_get_requests(
            path=f"/obp/v5.1.0/management/ai-threads/{thread_id}"
        )
        if response is None:
            raise ValueError(f"Failed to retrieve thread {thread_id}")
        import json
        return Thread(**json.loads(response))

    async def read_all(self) -> List[Thread]:
        """Retrieve all threads from OBP API."""
        # TODO: Implement OBP API endpoint for listing threads
        response = await self.obp_client.async_obp_get_requests(
            path="/obp/v5.1.0/management/ai-threads"
        )
        if response is None:
            return []
        import json
        data = json.loads(response)
        return [Thread(**item) for item in data.get('threads', [])]

    async def update(self, thread: Thread) -> None:
        """Update a thread in OBP API."""
        # TODO: Implement OBP API endpoint for thread update
        await self.obp_client.async_obp_requests(
            method="PUT",
            path=f"/obp/v5.1.0/management/ai-threads/{thread.id}",
            body=thread.model_dump_json()
        )

    async def delete(self, thread_id: UUID) -> None:
        """Delete a thread from OBP API."""
        # TODO: Implement OBP API endpoint for thread deletion
        await self.obp_client.async_obp_requests(
            method="DELETE",
            path=f"/obp/v5.1.0/management/ai-threads/{thread_id}",
            body=""
        )
