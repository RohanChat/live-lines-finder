from abc import ABC, abstractmethod
from typing import Any, Callable


class BaseMessagingClient(ABC):
    """Abstract interface for messaging backends."""

    @abstractmethod
    async def send_message(self, chat_id: Any, text: str, **kwargs) -> None:
        """Send a message to the given chat/user."""

    @abstractmethod
    def register_command_handler(self, command: str, handler: Callable) -> None:
        """Register a function for a command."""

    @abstractmethod
    def register_message_handler(self, filter_obj: Any, handler: Callable) -> None:
        """Register a general message handler."""

    @abstractmethod
    def register_callback_query_handler(self, handler: Callable) -> None:
        """Register a callback query handler."""

    @abstractmethod
    def start(self) -> None:
        """Start the messaging client."""
