from ..base import BaseMessagingClient


class iMessageBot(BaseMessagingClient):
    """Placeholder for future Slack integration."""

    def __init__(self, token: str) -> None:
        self.token = token
        # TODO: Initialize Slack client when implemented

    async def send_message(self, chat_id, text: str, **kwargs) -> None:
        raise NotImplementedError("Slack messaging not implemented yet")

    def register_command_handler(self, command: str, handler) -> None:
        raise NotImplementedError("Slack messaging not implemented yet")

    def register_message_handler(self, filter_obj, handler) -> None:
        raise NotImplementedError("Slack messaging not implemented yet")

    def register_callback_query_handler(self, handler) -> None:
        raise NotImplementedError("Slack messaging not implemented yet")

    def start(self) -> None:
        raise NotImplementedError("Slack messaging not implemented yet")
