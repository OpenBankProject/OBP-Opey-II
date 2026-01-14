from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any, Optional, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    ChannelVersions,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from client.obp_client import OBPClient
from checkpointer.entities import OpeyCheckpointEntity, OpeyCheckpointWriteEntity
from auth.admin_client import get_admin_client
class OBPCheckpointSaver(BaseCheckpointSaver[str]):
    """Checkpoint saver using OBP Dynamic Entities as a storage backend.
    
    This class provides an asynchronous interface for saving and retrieving checkpoints
    using OBP Dynamic Entities. It's designed for use in asynchronous environments.
    
    Architecture:
    - System-level dynamic entities are created once by an admin client (setup phase)
    - User-specific CRUD operations use a consent_id from config to create OBPClient
    - Each user gets their own CRUD endpoints for the dynamic entities once created
    - RunnableConfig only contains JSON-serializable data (consent_id string)
    
    Attributes:
        serde (JsonPlusSerializer): The serializer used for encoding/decoding checkpoints.
        lock (asyncio.Lock): Lock for thread-safe operations.
        is_setup (bool): Whether the dynamic entities have been created.
    
    Examples:
        Usage within StateGraph:
        
        ```python
        from langgraph.graph import StateGraph
        from checkpointer.obp_checkpoint_saver import OBPCheckpointSaver
        
        async def main():
            # Global checkpointer (stateless)
            saver = OBPCheckpointSaver()
            await saver.setup()  # Uses admin client to create system entities
            
            builder = StateGraph(int)
            builder.add_node("add_one", lambda x: x + 1)
            builder.set_entry_point("add_one")
            builder.set_finish_point("add_one")
            
            graph = builder.compile(checkpointer=saver)
            
            # Config contains only JSON-serializable data
            config = {
                "configurable": {
                    "thread_id": "thread-1",
                    "consent_id": "user-consent-123"  # JSON-serializable!
                }
            }
            result = await graph.ainvoke(1, config)
            print(result)
        ```
    """
    
    lock: asyncio.Lock
    is_setup: bool
    
    def __init__(self):
        """Initialize the checkpoint saver.
        
        Note: No client is stored - admin client is used only during setup,
        and user clients are passed via config for CRUD operations.
        """
        super().__init__()
        self.serde = JsonPlusSerializer()
        self.lock = asyncio.Lock()
        self.loop = asyncio.get_running_loop()
        self.is_setup = False
    
    def _get_client_from_config(self, config: RunnableConfig) -> OBPClient:
        """Create an OBPClient from the consent_id in config.
        
        Args:
            config: The runnable config containing the user's consent_id.
            
        Returns:
            A new OBPClient instance for the user.
            
        Raises:
            ValueError: If no consent_id is found in config.
        """
        from auth.auth import OBPConsentAuth
        
        consent_id = config.get("configurable", {}).get("consent_id")
        if not consent_id:
            raise ValueError(
                "consent_id must be provided in config['configurable']['consent_id']. "
                "This is required to create an authenticated OBPClient for checkpoint CRUD operations."
            )
        
        # Create auth and client from consent_id
        auth = OBPConsentAuth(consent_id=consent_id)
        return OBPClient(auth)
        
    async def _check_existing_setup(self, admin_client: OBPClient) -> bool:
        """
        Check if the required Dynamic Entities are already set up in OBP.
        Uses admin client to check system-level entities.
        
        Args:
            admin_client: The admin OBPClient for checking system entities.
        
        Returns:
            bool: True if setup exists, False otherwise.
        """
        try:
            response = await admin_client.get("/obp/v6.0.0/management/system-dynamic-entities")
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
    
    async def _create_dynamic_entities(self, admin_client: OBPClient) -> None:
        """Create the required Dynamic Entities in OBP.
        
        Uses admin client to create system-level entities.
        
        Args:
            admin_client: The admin OBPClient for creating system entities.
        """
        # Create OpeyCheckpoint entity
        await admin_client.post(
            path="/obp/v6.0.0/management/system-dynamic-entities",
            body=OpeyCheckpointEntity.to_obp_schema()
        )
        
        # Create OpeyCheckpointWrite entity
        await admin_client.post(
            path="/obp/v6.0.0/management/system-dynamic-entities",
            body=OpeyCheckpointWriteEntity.to_obp_schema()
        )
    
    async def setup(self) -> None:
        """Setup the Dynamic Entities in OBP if they do not exist.
        
        This method creates the necessary dynamic entities in OBP if they don't
        already exist. Uses admin client for system-level entity creation.
        Should be called once at application startup.
        """
        logger = logging.getLogger('checkpointer.obp_checkpoint_saver')
        
        async with self.lock:
            if self.is_setup:
                logger.debug("OBP checkpointer already set up, skipping")
                return
            
            logger.info("Setting up OBP checkpoint saver...")
            
            # Get admin client for setup operations
            try:
                admin_client = get_admin_client()
                logger.debug("Retrieved admin client for setup")
            except RuntimeError as e:
                logger.error("Failed to get admin client for checkpoint setup")
                raise ValueError(
                    "Admin client must be initialized for checkpoint saver setup. "
                    "This is required to create system-level dynamic entities."
                ) from e
            
            logger.info("Checking if dynamic entities already exist...")
            if await self._check_existing_setup(admin_client):
                logger.info("✓ Dynamic entities already exist, skipping creation")
                self.is_setup = True
                return
            
            logger.info("Creating dynamic entities for checkpointing...")
            logger.info(f"  - Creating {OpeyCheckpointEntity.obp_entity_name()} entity")
            logger.info(f"  - Creating {OpeyCheckpointWriteEntity.obp_entity_name()} entity")
            
            await self._create_dynamic_entities(admin_client)
            
            logger.info("✓ OBP checkpoint saver setup completed successfully")
            self.is_setup = True
    
    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """Get a checkpoint tuple from OBP.
        
        This method retrieves a checkpoint tuple based on the provided config.
        If the config contains a `checkpoint_id`, that specific checkpoint is retrieved.
        Otherwise, the latest checkpoint for the thread is retrieved.
        
        Args:
            config: The config to use for retrieving the checkpoint.
            
        Returns:
            The retrieved checkpoint tuple, or None if not found.
        """
        try:
            if asyncio.get_running_loop() is self.loop:
                raise asyncio.InvalidStateError(
                    "Synchronous calls to OBPCheckpointSaver are only allowed from a "
                    "different thread. From the main thread, use the async interface. "
                    "For example, use `await checkpointer.aget_tuple(...)` or `await "
                    "graph.ainvoke(...)`."
                )
        except RuntimeError:
            pass
        return asyncio.run_coroutine_threadsafe(
            self.aget_tuple(config), self.loop
        ).result()
    
    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        """List checkpoints from OBP.
        
        Args:
            config: Base configuration for filtering checkpoints.
            filter: Additional filtering criteria for metadata.
            before: If provided, only checkpoints before the specified checkpoint ID are returned.
            limit: Maximum number of checkpoints to return.
            
        Yields:
            An iterator of matching checkpoint tuples.
        """
        try:
            if asyncio.get_running_loop() is self.loop:
                raise asyncio.InvalidStateError(
                    "Synchronous calls to OBPCheckpointSaver are only allowed from a "
                    "different thread. From the main thread, use the async interface."
                )
        except RuntimeError:
            pass
        aiter_ = self.alist(config, filter=filter, before=before, limit=limit)
        while True:
            try:
                yield asyncio.run_coroutine_threadsafe(
                    anext(aiter_),  # type: ignore[arg-type]
                    self.loop,
                ).result()
            except StopAsyncIteration:
                break
    
    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Save a checkpoint to OBP.
        
        Args:
            config: The config to associate with the checkpoint.
            checkpoint: The checkpoint to save.
            metadata: Additional metadata to save with the checkpoint.
            new_versions: New channel versions as of this write.
            
        Returns:
            Updated configuration after storing the checkpoint.
        """
        return asyncio.run_coroutine_threadsafe(
            self.aput(config, checkpoint, metadata, new_versions), self.loop
        ).result()
    
    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store intermediate writes linked to a checkpoint.
        
        Args:
            config: Configuration of the related checkpoint.
            writes: List of writes to store.
            task_id: Identifier for the task creating the writes.
            task_path: Path of the task creating the writes.
        """
        return asyncio.run_coroutine_threadsafe(
            self.aput_writes(config, writes, task_id, task_path), self.loop
        ).result()
    
    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """Get a checkpoint tuple from OBP asynchronously.
        
        Args:
            config: The config to use for retrieving the checkpoint.
                   Must include 'consent_id' in configurable for creating user's OBPClient.
            
        Returns:
            The retrieved checkpoint tuple, or None if not found.
        """
        await self.setup()
        client = self._get_client_from_config(config)
        thread_id = str(config["configurable"]["thread_id"])
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)
        
        async with self.lock:
            # Query dynamic entities for checkpoints using user's client
            endpoint = f"/obp/v6.0.0/my/dynamic-entities/{OpeyCheckpointEntity.obp_entity_name()}"
            
            try:
                response = await client.get(endpoint)
                entities = response.json().get("dynamic_entities", [])
                
                # Filter checkpoints
                matching_checkpoints = [
                    e for e in entities
                    if e.get("thread_id") == thread_id
                    and e.get("checkpoint_ns") == checkpoint_ns
                    and (not checkpoint_id or e.get("checkpoint_id") == checkpoint_id)
                ]
                
                if not matching_checkpoints:
                    return None
                
                # Get latest if no specific checkpoint_id
                checkpoint_entity = max(
                    matching_checkpoints,
                    key=lambda x: x.get("checkpoint_id", "")
                )
                
                # Update config with found checkpoint_id
                if not get_checkpoint_id(config):
                    config = {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": checkpoint_entity["checkpoint_id"],
                        }
                    }
                
                # Get pending writes
                writes_endpoint = f"/obp/v6.0.0/my/dynamic-entities/{OpeyCheckpointWriteEntity.obp_entity_name()}"
                writes_response = await client.get(writes_endpoint)
                write_entities = writes_response.json().get("dynamic_entities", [])
                
                pending_writes = [
                    w for w in write_entities
                    if w.get("thread_id") == thread_id
                    and w.get("checkpoint_ns") == checkpoint_ns
                    and w.get("checkpoint_id") == checkpoint_entity["checkpoint_id"]
                ]
                
                # Sort writes by task_id and idx
                pending_writes.sort(key=lambda w: (w.get("task_id", ""), w.get("idx", 0)))
                
                # Deserialize checkpoint and metadata
                checkpoint_data = self.serde.loads(checkpoint_entity["checkpoint_data"])
                metadata = json.loads(checkpoint_entity.get("metadata", "{}"))
                
                parent_config = None
                if checkpoint_entity.get("parent_checkpoint_id"):
                    parent_config = {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": checkpoint_entity["parent_checkpoint_id"],
                        }
                    }
                
                return CheckpointTuple(
                    config=config,
                    checkpoint=checkpoint_data,
                    metadata=cast(CheckpointMetadata, metadata),
                    parent_config=parent_config,
                    pending_writes=[
                        (w["task_id"], w["channel"], self.serde.loads(w["value"]))
                        for w in pending_writes
                    ],
                )
            except Exception:
                return None
    
    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """List checkpoints from OBP asynchronously.
        
        Args:
            config: Base configuration for filtering checkpoints.
                   Must include 'consent_id' in configurable for creating user's OBPClient.
            filter: Additional filtering criteria for metadata.
            before: If provided, only checkpoints before the specified checkpoint ID are returned.
            limit: Maximum number of checkpoints to return.
            
        Yields:
            An asynchronous iterator of matching checkpoint tuples.
        """
        await self.setup()
        if not config:
            raise ValueError("Config with obp_client is required for listing checkpoints")
        
        client = self._get_client_from_config(config)
        thread_id = str(config["configurable"]["thread_id"])
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        before_id = get_checkpoint_id(before) if before else None
        
        async with self.lock:
            endpoint = f"/obp/v6.0.0/my/dynamic-entities/{OpeyCheckpointEntity.obp_entity_name()}"
            response = await client.get(endpoint)
            entities = response.json().get("dynamic_entities", [])
            
            # Filter checkpoints
            filtered = entities
            if thread_id:
                filtered = [e for e in filtered if e.get("thread_id") == thread_id]
            if checkpoint_ns:
                filtered = [e for e in filtered if e.get("checkpoint_ns") == checkpoint_ns]
            if before_id:
                filtered = [e for e in filtered if e.get("checkpoint_id", "") < before_id]
            
            # Apply metadata filter
            if filter:
                filtered = [
                    e for e in filtered
                    if all(
                        json.loads(e.get("metadata", "{}")).get(k) == v
                        for k, v in filter.items()
                    )
                ]
            
            # Sort by checkpoint_id descending
            filtered.sort(key=lambda x: x.get("checkpoint_id", ""), reverse=True)
            
            # Apply limit
            if limit:
                filtered = filtered[:limit]
            
            # Get all writes once
            writes_endpoint = f"/obp/v6.0.0/my/dynamic-entities/{OpeyCheckpointWriteEntity.obp_entity_name()}"
            writes_response = await client.get(writes_endpoint)
            all_writes = writes_response.json().get("dynamic_entities", [])
            
            for checkpoint_entity in filtered:
                thread_id = checkpoint_entity["thread_id"]
                checkpoint_ns = checkpoint_entity["checkpoint_ns"]
                checkpoint_id = checkpoint_entity["checkpoint_id"]
                
                # Get writes for this checkpoint
                pending_writes = [
                    w for w in all_writes
                    if w.get("thread_id") == thread_id
                    and w.get("checkpoint_ns") == checkpoint_ns
                    and w.get("checkpoint_id") == checkpoint_id
                ]
                pending_writes.sort(key=lambda w: (w.get("task_id", ""), w.get("idx", 0)))
                
                checkpoint_data = self.serde.loads(checkpoint_entity["checkpoint_data"])
                metadata = json.loads(checkpoint_entity.get("metadata", "{}"))
                
                parent_config = None
                if checkpoint_entity.get("parent_checkpoint_id"):
                    parent_config = {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": checkpoint_entity["parent_checkpoint_id"],
                        }
                    }
                
                yield CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": checkpoint_id,
                        }
                    },
                    checkpoint=checkpoint_data,
                    metadata=cast(CheckpointMetadata, metadata),
                    parent_config=parent_config,
                    pending_writes=[
                        (w["task_id"], w["channel"], self.serde.loads(w["value"]))
                        for w in pending_writes
                    ],
                )
    
    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Save a checkpoint to OBP asynchronously.
        
        Args:
            config: The config to associate with the checkpoint.
                   Must include 'consent_id' in configurable for creating user's OBPClient.
            checkpoint: The checkpoint to save.
            metadata: Additional metadata to save with the checkpoint.
            new_versions: New channel versions as of this write.
            
        Returns:
            Updated configuration after storing the checkpoint.
        """
        await self.setup()
        client = self._get_client_from_config(config)
        thread_id = str(config["configurable"]["thread_id"])
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        
        checkpoint_entity = OpeyCheckpointEntity(
            thread_id=thread_id,
            checkpoint_id=checkpoint["id"],
            checkpoint_ns=checkpoint_ns,
            parent_checkpoint_id=config["configurable"].get("checkpoint_id"),
            checkpoint_data=self.serde.dumps(checkpoint),
            metadata=json.dumps(get_checkpoint_metadata(config, metadata)),
        )
        
        async with self.lock:
            endpoint = f"/obp/v6.0.0/my/dynamic-entities/{OpeyCheckpointEntity.obp_entity_name()}"
            await client.post(endpoint, body=checkpoint_entity.model_dump(mode="json"))
        
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }
    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store intermediate writes linked to a checkpoint asynchronously.
        
        Args:
            config: Configuration of the related checkpoint.
                   Must include 'consent_id' in configurable for creating user's OBPClient.
            writes: List of writes to store.
            task_id: Identifier for the task creating the writes.
            task_path: Path of the task creating the writes.
        """
        await self.setup()
        client = self._get_client_from_config(config)
        thread_id = str(config["configurable"]["thread_id"])
        checkpoint_ns = str(config["configurable"].get("checkpoint_ns", ""))
        checkpoint_id = str(config["configurable"]["checkpoint_id"])
        
        write_entities = []
        for idx, (channel, value) in enumerate(writes):
            write_entity = OpeyCheckpointWriteEntity(
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                checkpoint_ns=checkpoint_ns,
                task_id=task_id,
                idx=WRITES_IDX_MAP.get(channel, idx),
                channel=channel,
                value=self.serde.dumps(value),
            )
            write_entities.append(write_entity)
        
        async with self.lock:
            endpoint = f"/obp/v6.0.0/my/dynamic-entities/{OpeyCheckpointWriteEntity.obp_entity_name()}"
            for entity in write_entities:
                await self.client.post(endpoint, body=entity.model_dump(mode="json"))
    
    def get_next_version(self, current: str | None, channel: None) -> str:
        """Generate the next version ID for a channel.
        
        Args:
            current: The current version identifier of the channel.
            
        Returns:
            The next version identifier, monotonically increasing.
        """
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current
        else:
            current_v = int(current.split(".")[0])
        next_v = current_v + 1
        next_h = random.random()
        return f"{next_v:032}.{next_h:016}"
