from abc import ABC, abstractmethod
from typing import List, Dict
from uuid import UUID
from .model import Thread
from client.obp_client import OBPClient

class IThreadBackend(ABC):
    @abstractmethod
    async def create(self, thread: Thread) -> None:
        """Create a new thread with the given ID and data."""
        pass

    @abstractmethod
    async def read(self, thread_id: UUID) -> Thread:
        """Read the thread data for the given ID."""
        pass

    @abstractmethod
    async def read_all(self) -> List[Thread]:
        """Read all threads."""
        pass

    @abstractmethod
    async def update(self, thread: Thread) -> None:
        """Update the thread data for the given ID."""
        pass

    @abstractmethod
    async def delete(self, thread_id: UUID) -> None:
        """Delete the thread with the given ID."""
        pass

class OBPThreadBackend(IThreadBackend):
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

class ThreadManager:
    def __init__(self, backend: IThreadBackend):
        """Initialize the ThreadManager with a backend implementation."""
        self.backend = backend
        self.current_thread_id: UUID | None = None

    async def get_threads_for_user(self, user_id: str) -> List[Thread]:
        """Filter threads by user_id from metadata."""
        all_threads = await self.backend.read_all()
        return [t for t in all_threads if t.metadata and t.metadata.get('user_id') == user_id]
    
    def switch_to_thread(self, thread_id: UUID) -> None:
        """Set the current active thread."""
        self.current_thread_id = thread_id
    
    async def create_new_thread(self, thread: Thread) -> UUID:
        """Persist a new thread and return its ID."""
        await self.backend.create(thread)
        return thread.id
    
    async def delete_thread(self, thread_id: UUID) -> None:
        """Remove a thread from persistence."""
        await self.backend.delete(thread_id)
        if self.current_thread_id == thread_id:
            self.current_thread_id = None
        raise NotImplementedError("This method is not implemented yet")
