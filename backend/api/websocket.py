"""WebSocket 进度推送管理"""

from __future__ import annotations

import asyncio
import json
from typing import Set

from fastapi import WebSocket


class ConnectionManager:
    """管理 WebSocket 连接，广播进度消息"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        """向所有连接广播消息"""
        dead = set()
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        self.active_connections -= dead


manager = ConnectionManager()
