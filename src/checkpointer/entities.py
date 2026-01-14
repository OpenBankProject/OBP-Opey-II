from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from client.obp_client import OBPClient
import json

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
        json_schema = cls.model_json_schema()
        
        # Define examples for each field
        examples = {
            "thread_id": "thread-abc-123",
            "checkpoint_id": "1ef89abc-def0-6789-abcd-ef0123456789",
            "checkpoint_ns": "",
            "parent_checkpoint_id": "1ef89abc-def0-6789-abcd-ef0123456788",
            "checkpoint_data": '{"v": 1, "ts": "2024-01-01T00:00:00.000Z"}',
            "metadata": '{"source": "loop", "step": 1}',
            "created_at": "2024-01-01T00:00:00.000000"
        }
        
        return {
            "hasPersonalEntity": True,
            cls.obp_entity_name(): {
                "description": cls.__doc__.strip(),
                "required": json_schema["required"],
                "properties": {
                    k: {
                        "type": v.get("type", "string"),
                        "description": v.get("description", ""),
                        "example": examples.get(k, "")
                    }
                    for k, v in json_schema["properties"].items()
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
        json_schema = cls.model_json_schema()
        
        # Define examples for each field
        examples = {
            "thread_id": "thread-abc-123",
            "checkpoint_id": "1ef89abc-def0-6789-abcd-ef0123456789",
            "checkpoint_ns": "",
            "task_id": "task-node-1",
            "idx": 0,
            "channel": "messages",
            "value": '["AI", {"content": "Hello"}]'
        }
        
        return {
            "hasPersonalEntity": True,
            cls.obp_entity_name(): {
                "description": cls.__doc__.strip(),
                "required": json_schema["required"],
                "properties": {
                    k: {
                        "type": v.get("type", "string"),
                        "description": v.get("description", ""),
                        "example": examples.get(k, "" if v.get("type") == "string" else 0)
                    }
                    for k, v in json_schema["properties"].items()
                }
            }
        }

class DynamicEntitiesManager:
    """Wrapper for DynamicEntities CRUD endpoints."""
    def __init__(self, obp_client: OBPClient, endpoint_url: str):
        
        self.endpoint_url = endpoint_url
        self.client = obp_client
        

    async def create(self, entity: OpeyCheckpointEntity | OpeyCheckpointWriteEntity):
        await self.client.post(
            path=self.endpoint_url,
            body=entity.model_dump()
        )
        
    async def delete(self, entity_id: str):
        await self.client.delete(
            path=f"{self.endpoint_url}/{entity_id}"
        )
    
    async def read(self, entity_id: str) -> dict:
        response = await self.client.get(
            path=f"{self.endpoint_url}/{entity_id}"
        )
        return response.json()

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
