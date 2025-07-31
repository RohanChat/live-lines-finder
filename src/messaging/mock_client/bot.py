from typing import Any, Callable, List, Tuple
import asyncio

from messaging.base import BaseMessagingClient


class MockMessagingClient(BaseMessagingClient):
    def __init__(self):
        # store the handlers you register
        self._cmd_handlers: List[Tuple[str, Callable]] = []
        self._msg_handlers: List[Tuple[Callable[[Any], bool], Callable]] = []
        self.sent: List[Tuple[Any,str,dict]] = []

    async def send_message(self, chat_id: Any, text: str, **kwargs) -> None:
        # capture outbound messages
        self.sent.append((chat_id, text, kwargs))

    def register_command_handler(self, command: str, handler: Callable) -> None:
        self._cmd_handlers.append((command, handler))

    def register_message_handler(self, filter_obj: Any, handler: Callable) -> None:
        self._msg_handlers.append((filter_obj, handler))

    def register_callback_query_handler(self, handler: Callable) -> None:
        # ignore for now
        pass

    def start(self) -> None:
        # we don’t automatically read stdin—tests will drive simulate_*()
        pass

    def simulate_command(self, command: str, args: list[str]=[], chat_id: Any=1):
        """Synchronously invoke your /cmd handlers."""
        class C: pass
        update = C(); update.effective_chat=type("c",(object,),{"id":chat_id})
        context = type("ctx",(object,),{"args": args})
        for cmd, fn in self._cmd_handlers:
            if cmd == command:
                asyncio.run(fn(update, context))

    def simulate_message(self, text: str, chat_id: Any=1):
        """Synchronously invoke any message handler whose filter passes."""
        class M: pass
        update = M(); update.effective_chat=type("c",(object,),{"id":chat_id}); update.message=type("m",(object,),{"text": text})
        context = None
        for flt, fn in self._msg_handlers:
            # if flt is a callable filter, call it
            ok = flt(update.message) if callable(flt) else True
            if ok:
                asyncio.run(fn(update, context))