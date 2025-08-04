from ..base import BaseMessagingClient


class iMessageBot(BaseMessagingClient):
    """Placeholder for future imessage integration."""

    def __init__(self, token: str) -> None:
        self.token = token
        # TODO: Initialize imessage client when implemented

    def register_message_handler(self, command: str, handler) -> None:
        raise NotImplementedError("imessage messaging not implemented yet")
    
    def register_command_handler(self, command: str, handler) -> None:
        raise NotImplementedError("imessage messaging not implemented yet")

    async def send_message(self, chat_id, text: str, **kwargs) -> None:
        raise NotImplementedError("imessage messaging not implemented yet")

    def start(self) -> None:
        raise NotImplementedError("imessage messaging not implemented yet")
