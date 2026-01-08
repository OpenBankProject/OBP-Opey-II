from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class OpeyCheckpointEntity(BaseModel):
    """OBP Dynamic Entity representation of a LangGraph checkpoint."""
    
    thread_id: str = Field(description="Thread identifier")
    checkpoint_id: str = Field(description="Unique checkpoint ID (UUID)")
    checkpoint_ns: str = Field(description="Checkpoint namespace")
    parent_checkpoint_id: Optional[str] = Field(description="Parent checkpoint ID for history.")
    checkpoint_data: str = Field(description="Serialized checkpoint TypedDict")
    metadata: str = Field(description="Serialized CheckpointMetadata")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="ISO timestamp")

    @classmethod
    def obp_entity_name(cls) -> str:
        return "OpeyCheckpoint"
    
    @classmethod
    def to_obp_schema(cls) -> dict:
        return {
            "hasPersonalEntity": True,
            cls.obp_entity_name(): {
                "description": "LangGraph checkpoint snapshots for Opey AI conversations",
                "required": ["thread_id", "checkpoint_id", "checkpoint_ns", "checkpoint_data"],
                "properties": {
                    "thread_id": {"type": "string", "description": "Thread identifier"},
                    "checkpoint_id": {"type": "string", "description": "Unique checkpoint ID (UUID)"},
                    "checkpoint_ns": {"type": "string", "description": "Checkpoint namespace"},
                    "parent_checkpoint_id": {"type": "string", "description": "Parent checkpoint ID for history"},
                    "checkpoint_data": {"type": "string", "description": "JSON-serialized checkpoint (channel_values, versions, etc.)"},
                    "metadata": {"type": "string", "description": "JSON-serialized metadata (step, source, writes)"},
                    "created_at": {"type": "string", "description": "ISO timestamp"}
                }
            }
        }
        

class OpeyCheckpointWriteEntity(BaseModel):
    """OBP Dynamic Entity representation of a pending LangGraph checkpoint write."""
    
    thread_id: str = Field(description="Thread identifier")
    checkpoint_id: str = Field(description="Checkpoint ID this write belongs to")
    checkpoint_ns: str = Field(description="Checkpoint namespace")
    task_id: str = Field(description="Task that produced this write")
    idx: int = Field(description="Write index within task")
    channel: str = Field(description="Channel name")
    value: str = Field(description="Serialized write value")

    @classmethod
    def obp_entity_name(cls) -> str:
        return "OpeyCheckpointWrite"
    
    @classmethod
    def to_obp_schema(cls) -> dict:
        """OBP Dynamic Entity schema definition."""
        return {
            "hasPersonalEntity": True,
            cls.obp_entity_name(): {
                "description": "Pending writes for LangGraph checkpoints",
                "required": ["thread_id", "checkpoint_id", "checkpoint_ns", "task_id", "channel", "value", "idx"],
                "properties": {
                    "thread_id": {"type": "string"},
                    "checkpoint_id": {"type": "string"},
                    "checkpoint_ns": {"type": "string"},
                    "task_id": {"type": "string", "description": "Task that produced this write"},
                    "idx": {"type": "integer", "description": "Write index within task"},
                    "channel": {"type": "string", "description": "Channel name"},
                    "value": {"type": "string", "description": "Serialized write value"}
                }
            }
        }


opey_checkpoint_entity = {
  "hasPersonalEntity": True,
  "OpeyCheckpoint": {
    "description": "LangGraph checkpoint snapshots for Opey AI conversations",
    "required": ["thread_id", "checkpoint_id", "checkpoint_ns", "checkpoint_data"],
    "properties": {
      "thread_id": {"type": "string", "description": "Thread identifier"},
      "checkpoint_id": {"type": "string", "description": "Unique checkpoint ID (UUID)"},
      "checkpoint_ns": {"type": "string", "description": "Checkpoint namespace"},
      "parent_checkpoint_id": {"type": "string", "description": "Parent checkpoint ID for history"},
      "checkpoint_data": {"type": "string", "description": "JSON-serialized checkpoint (channel_values, versions, etc.)"},
      "metadata": {"type": "string", "description": "JSON-serialized metadata (step, source, writes)"},
      "created_at": {"type": "string", "description": "ISO timestamp"}
    }
  }
}

opey_checkpoint_write_entity = {
  "hasPersonalEntity": True,
  "OpeyCheckpointWrite": {
    "description": "Pending writes for LangGraph checkpoints",
    "required": ["thread_id", "checkpoint_id", "checkpoint_ns", "task_id", "channel", "value"],
    "properties": {
      "thread_id": {"type": "string"},
      "checkpoint_id": {"type": "string"},
      "checkpoint_ns": {"type": "string"},
      "task_id": {"type": "string", "description": "Task that produced this write"},
      "idx": {"type": "integer", "description": "Write index within task"},
      "channel": {"type": "string", "description": "Channel name"},
      "value": {"type": "string", "description": "JSON-serialized write value"}
    }
  }
}