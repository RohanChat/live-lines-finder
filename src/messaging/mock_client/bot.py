from typing import Any, Callable, List, Tuple
import asyncio

from messaging.base import BaseMessagingClient
from config import Config


class MockMessagingClient(BaseMessagingClient):
    def __init__(self, chat_id: str = Config.MOCK_CHAT_ID):
        # store the handlers you register
        self._cmd_handlers: List[Tuple[str, Callable]] = []
        self._msg_handlers: List[Tuple[Callable[[Any], bool], Callable]] = []
        self.sent: List[Tuple[Any,str,dict]] = []
        self.chat_id = chat_id

    def register_message_handler(self, filter: Callable[[Any], bool], handler: Callable) -> None:
        """Register a message handler with a filter."""
        if not callable(filter):
            raise ValueError("Filter must be a callable that takes a message and returns a boolean.")
        if not callable(handler):
            raise ValueError("Handler must be a callable that takes (update, context).")
        self._msg_handlers.append((filter, handler))

    def register_command_handler(self, command: str, handler: Callable) -> None:
        """Register a command handler for the given command."""
        if not isinstance(command, str) or not command.startswith('/'):
            raise ValueError("Command must be a string starting with '/'")
        if not callable(handler):
            raise ValueError("Handler must be a callable that takes (update, context).")
        self._cmd_handlers.append((command, handler))

    async def send_message(self, chat_id: Any, text: str, **kwargs) -> None:
        # capture outbound messages
        self.sent.append((chat_id, text, kwargs))

    def start(self) -> None:
        print("Mock Messaging CLI – type a message and press enter (Ctrl-C to quit).")
        try:
            while True:
                text = input("YOU> ").strip()
                if not text:
                    continue

                # Drive the normal message‐handler flow
                self.simulate_message(text)

                # Pull out and print any replies
                for _, reply, _ in self.sent:
                    print(f"BOT> {reply}")

                # Clear out history so we only show new messages next round
                self.sent.clear()

        except KeyboardInterrupt:
            print("\nExiting mock client.")

    def simulate_message(self, text: str, chat_id: str = None):
        """Synchronously invoke any message handler whose filter passes."""
        if chat_id is None:
            chat_id = self.chat_id
        class M: pass
        update = M(); update.effective_chat=type("c",(object,),{"id":chat_id}); update.message=type("m",(object,),{"text": text})
        context = None
        for flt, fn in self._msg_handlers:
            # if flt is a callable filter, call it
            ok = flt(update.message) if callable(flt) else True
            if ok:
                asyncio.run(fn(update, context))