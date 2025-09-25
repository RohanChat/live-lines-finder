from abc import ABC, abstractmethod
from typing import Any, Callable


class BaseMessagingClient(ABC):
    """Abstract interface for messaging backends."""

    @abstractmethod
    def register_message_handler(self, command: str, handler: Callable) -> None:
        """Register a message handler for the given command."""

    @abstractmethod
    def register_command_handler(self, command: str, handler: Callable) -> None:
        """Register a command handler for the given command."""

    @abstractmethod
    async def send_message(self, chat_id: Any, text: str, **kwargs) -> None:
        """Send a message to the given chat/user."""

    @abstractmethod
    def start(self) -> None:
        """Start the messaging client."""
