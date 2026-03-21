from src.checkpointer.entities import OpeyCheckpointEntity, OpeyCheckpointWriteEntity


def test_opey_checkpoint_entity_schema():
    schema = OpeyCheckpointEntity.to_obp_schema()
    
    assert schema["hasPersonalEntity"] is True
    assert schema["OpeyCheckpoint"]["description"] == "OBP Dynamic Entity representation of a LangGraph checkpoint."
    assert set(schema["OpeyCheckpoint"]["required"]) == {
        "thread_id", "checkpoint_id", "checkpoint_ns", 
        "parent_checkpoint_id", "checkpoint_data", "metadata"
    }
    assert "created_at" in schema["OpeyCheckpoint"]["properties"]
    assert schema["OpeyCheckpoint"]["properties"]["checkpoint_data"]["description"] == "Serialized checkpoint TypedDict"
    

def test_opey_checkpoint_write_entity_schema():
    schema = OpeyCheckpointWriteEntity.to_obp_schema()
    
    assert schema["hasPersonalEntity"] is True
    assert schema["OpeyCheckpointWrite"]["description"] == "OBP Dynamic Entity representation of a pending LangGraph checkpoint write."
    assert set(schema["OpeyCheckpointWrite"]["required"]) == {
        "thread_id", "checkpoint_id", "checkpoint_ns", 
        "task_id", "idx", "channel", "value"
    }
    assert all(
        prop in schema["OpeyCheckpointWrite"]["properties"] 
        for prop in ["thread_id", "checkpoint_id", "task_id", "idx", "channel", "value"]
    )