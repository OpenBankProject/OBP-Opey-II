from typing import Iterator, Optional, Sequence
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    ChannelVersions,
    PendingWrite
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from src.client.obp_client import OBPClient
from src.checkpointer.entities import OpeyCheckpointEntity, OpeyCheckpointWriteEntity
from src.auth.admin_client import get_admin_client
class OBPCheckpointSaver(BaseCheckpointSaver):
    """Checkpoint saver using OBP Dynamic Entitites as a storage backend."""
    
    def __init__(self, client: OBPClient):
        super().__init__()
        if not client:
            try:
                client = get_admin_client()
            except RuntimeError as e:
                raise ValueError("An OBPClient must be provided or the admin client must be initialized.") from e
        
        self.client = client
        self.is_setup = False
        self.serde = JsonPlusSerializer()
        
    async def _check_existing_setup(self) -> bool:
        """
        Check if the required Dynamic Entities are already set up in OBP.
        
        Returns:
            bool: True if setup exists, False otherwise.
        """
        try:
            response = await self.client.get("/obp/v6.0.0/management/system-dynamic-entities")
            response_data = response.json()
        except Exception as e:
            raise RuntimeError(f"Error checking existing OBP setup: {e}") from e
        
        if not response_data or not isinstance(response_data, dict):
            return False
        
        existing_entities = response_data.get("dynamic_entities", [])
        required_entities = {OpeyCheckpointEntity.obp_entity_name(), OpeyCheckpointWriteEntity.obp_entity_name()}
        
        for entity in existing_entities:
            entity_name = next(iter(entity))
            if entity_name in required_entities:
                required_entities.remove(entity_name)
        
        return len(required_entities) == 0    
    
    def setup(self) -> None:
        """
        Setup the Dynamic Entities in OBP if they do not exist.
        Needs to use an admin OBP client to create the system level entities.
        """
        if self.is_setup:
            return
        
        
        
        
    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Store a checkpoint on OBP."""
