from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Optional
from datetime import datetime, UTC
import asyncio

from ..base import OddsFeed
from ..models import FeedDelta

UpdateHandler = Callable[[FeedDelta], Awaitable[None]]

class WebhookFeed(OddsFeed, ABC):
    def __init__(self) -> None:
        self._on_update: Optional[UpdateHandler] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def on_update(self, handler: UpdateHandler) -> None:
        self._on_update = handler

    async def start(self, q) -> None:
        if self._running: return
        self._running = True
        await self._connect()
        await self._subscribe(q)
        self._task = asyncio.create_task(self._pump())

    async def stop(self) -> None:
        self._running = False
        if self._task: self._task.cancel()
        await self._disconnect()

    async def _pump(self) -> None:
        try:
            async for raw in self._incoming():
                for delta in self._parse_message(raw):
                    delta.received_at = datetime.now(UTC)
                    if self._on_update: await self._on_update(delta)
        except asyncio.CancelledError:
            pass

    # provider-specific transport
    @abstractmethod
    async def _connect(self) -> None: ...
    @abstractmethod
    async def _disconnect(self) -> None: ...
    @abstractmethod
    async def _subscribe(self, q) -> None: ...
    @abstractmethod
    async def _incoming(self): yield b""
    @abstractmethod
    def _parse_message(self, raw) -> list[FeedDelta]: return []