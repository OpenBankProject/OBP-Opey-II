from typing import List
from uuid import UUID
from .backends.backend import ThreadBackend
from .model import Thread


class ThreadManager:
    def __init__(self, backend: ThreadBackend):
        """Initialize the ThreadManager with a backend implementation."""
        self.backend = backend
        self.available_threads: List[Thread] = []
        self.current_thread_id: UUID | None = None

    
    def switch_to_thread(self, thread_id: UUID) -> None:
        """Set the current active thread."""
        self.current_thread_id = thread_id
    
    async def create_new_thread(self, thread: Thread, switch_to_new: bool = False) -> UUID:
        """Persist a new thread and return its ID."""
        await self.backend.create(thread)
        await self.refresh_threads()
        
        if switch_to_new:
            self.current_thread_id = thread.id
        
        return thread.id
    
    async def refresh_threads(self) -> None:
        """Refresh the list of available threads from the backend."""
        self.available_threads = await self.backend.read_all()
    
    async def delete_thread(self, thread_id: UUID) -> None:
        """Remove a thread from persistence."""
        await self.backend.delete(thread_id)
        if self.current_thread_id == thread_id:
            self.current_thread_id = None
            
        await self.refresh_threads()
        
    async def init_thread_database(self) -> None:
        """Initialize the thread database."""
        await self.backend.initialize()
