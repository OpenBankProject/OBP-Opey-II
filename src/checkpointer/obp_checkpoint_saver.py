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

from src.client import obp_client
from src.checkpointer.entities import OpeyCheckpointEntity, OpeyCheckpointWriteEntity

class OBPCheckpointSaver(BaseCheckpointSaver):
    """Checkpoint saver using OBP Dynamic Entitites as a storage backend."""
    
    def __init__(self, client: OBPClient):
        super().__init__()
        self.client = client
        self.is_setup = False
        self.serde = JsonPlusSerializer()
        
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
