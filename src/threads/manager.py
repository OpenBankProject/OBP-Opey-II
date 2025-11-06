from typing import List
from uuid import UUID
from .backends.backend import ThreadBackend
from .model import Thread


class ThreadManager:
    def __init__(self, backend: ThreadBackend):
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
