from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from src.client.obp_client import OBPClient

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
        return {
            "hasPersonalEntity": True,
            cls.obp_entity_name(): {
                "description": cls.__doc__.strip(),
                "required": json_schema["required"],
                "properties": {
                    k: {"type": v.get("type", "string"), "description": v.get("description", "")}
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
        return {
            "hasPersonalEntity": True,
            cls.obp_entity_name(): {
                "description": cls.__doc__.strip(),
                "required": json_schema["required"],
                "properties": {
                    k: {"type": v.get("type", "string"), "description": v.get("description", "")}
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
        await self.client.async_obp_requests(
            method="POST",
            body=str(entity.model_dump()),
            path=self.endpoint_url
        )
        
    async def delete(self, entity_id: str):
        await self.client.async_obp_requests(
            method="DELETE",
            body="",
            path=f"{self.endpoint_url}/{entity_id}"
        )
    
    async def read(self, entity_id: str) -> dict:
        response = await self.client.async_obp_requests(
            method="GET",
            body="",
            path=f"{self.endpoint_url}/{entity_id}"
        )
        return response

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
