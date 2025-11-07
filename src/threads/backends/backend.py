from abc import ABC, abstractmethod
from ..model import Thread
from typing import List
from uuid import UUID

class ThreadBackend(ABC):
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