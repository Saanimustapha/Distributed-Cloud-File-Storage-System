from typing import Dict, Set
from fastapi import WebSocket
import json

class WSManager:
    def __init__(self):
        self.user_sockets: Dict[int, Set[WebSocket]] = {}

    async def connect(self, user_id: int, ws: WebSocket):
        await ws.accept()
        self.user_sockets.setdefault(user_id, set()).add(ws)

    def disconnect(self, user_id: int, ws: WebSocket):
        if user_id in self.user_sockets:
            self.user_sockets[user_id].discard(ws)
            if not self.user_sockets[user_id]:
                del self.user_sockets[user_id]

    async def send_to_user(self, user_id: int, payload: dict):
        sockets = list(self.user_sockets.get(user_id, []))
        if not sockets:
            return
        msg = json.dumps(payload, default=str)
        for ws in sockets:
            try:
                await ws.send_text(msg)
            except Exception:
                # ignore broken sockets; cleanup happens on disconnect
                pass

ws_manager = WSManager()
