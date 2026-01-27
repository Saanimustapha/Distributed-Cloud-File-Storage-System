from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session

from control_plane.db.session import get_db
from control_plane.services.web_socket_manager import ws_manager
from control_plane.core.security import decode_access_token 

router = APIRouter()

@router.websocket("/ws/notifications")
async def notifications_ws(ws: WebSocket, db: Session = Depends(get_db)):
    # token passed as ws://host/ws/notifications?token=...
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=1008)
        return

    # decode token -> get user_id (adjust to your JWT payload)
    try:
        payload = decode_access_token(token)  # must return dict with "sub" or "user_id"
        user_id = int(payload.get("user_id") or payload.get("sub"))
    except Exception:
        await ws.close(code=1008)
        return

    await ws_manager.connect(user_id, ws)

    try:
        while True:
            # Keep connection alive; optionally receive pings from client
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(user_id, ws)
