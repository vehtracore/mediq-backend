from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.concurrency import run_in_threadpool
from typing import List, Dict, Optional
import json
import logging
import traceback
from datetime import datetime

# 1. DB Imports
from app.core.database import engine, get_db
from sqlalchemy.orm import sessionmaker, Session
from app.models.message import Message
from app.models.appointment import Appointment
from app.models.user import User
from app.api import deps
from app.services.appointment_access import require_consultation_access

logger = logging.getLogger("uvicorn.error")

import sys
# Force unbuffered stdout for Render
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

# Create local session maker
WsSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

router = APIRouter()

# --- Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        # Track which user IDs are connected per appointment
        self.connected_users: Dict[str, set] = {}

    async def connect(self, websocket: WebSocket, appointment_id: str, user_id: int):
        if appointment_id not in self.active_connections:
            self.active_connections[appointment_id] = []
            self.connected_users[appointment_id] = set()
        self.active_connections[appointment_id].append(websocket)
        self.connected_users[appointment_id].add(user_id)

        # Broadcast presence: notify everyone in the room that this user is online
        presence_online = {"type": "presence", "status": "online", "user_id": user_id}
        await self.broadcast(presence_online, appointment_id)

    async def disconnect(self, websocket: WebSocket, appointment_id: str, user_id: int):
        if appointment_id in self.active_connections:
            if websocket in self.active_connections[appointment_id]:
                self.active_connections[appointment_id].remove(websocket)
            self.connected_users[appointment_id].discard(user_id)

            # Broadcast presence: notify remaining users that this user is offline
            if self.active_connections[appointment_id]:
                presence_offline = {"type": "presence", "status": "offline", "user_id": user_id}
                await self.broadcast(presence_offline, appointment_id)

            if not self.active_connections[appointment_id]:
                del self.active_connections[appointment_id]
                del self.connected_users[appointment_id]

    def is_user_connected(self, appointment_id: str, user_id: int) -> bool:
        """Check if a specific user is connected to the given appointment chat."""
        return user_id in self.connected_users.get(appointment_id, set())

    async def broadcast(self, message: dict, appointment_id: str):
        if appointment_id in self.active_connections:
            for connection in self.active_connections[appointment_id][:]:
                try:
                    await connection.send_text(json.dumps(message))
                except Exception as e:
                    logger.warning("[WS] Broadcast send failed, removing dead socket: %s", e)
                    await self.disconnect(connection, appointment_id, 0)

manager = ConnectionManager()

# --- 🧪 DIAGNOSTIC ENDPOINT ---
@router.get("/test")
def chat_test():
    return {"status": "ok", "message": "Chat Router is Online"}

# --- History Endpoint (Cursor-Based Pagination) ---
@router.get("/history/{appointment_id}")
def get_chat_history(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    cursor: Optional[str] = Query(None, description="ID of the last message from the previous page"),
    limit: int = Query(20, ge=1, le=100, description="Number of messages per page"),
):
    require_consultation_access(
        db,
        appointment_id,
        current_user,
        allow_completed=True,
    )
    query = db.query(Message).filter(Message.appointment_id == appointment_id)

    # If cursor is provided, find the cursor message's timestamp and filter older messages
    if cursor is not None:
        cursor_message = (
            db.query(Message)
            .filter(
                Message.id == int(cursor),
                Message.appointment_id == appointment_id,
            )
            .first()
        )
        if cursor_message:
            query = query.filter(Message.created_at < cursor_message.created_at)

    # Order by newest first, fetch limit + 1 to check for more pages
    messages = query.order_by(Message.created_at.desc()).limit(limit + 1).all()

    # Determine if there are more messages beyond this page
    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]  # Trim the extra record

    # Reverse to chronological order for the frontend
    messages.reverse()

    # Serialize
    serialized = [
        {
            "id": m.id,
            "appointment_id": m.appointment_id,
            "sender_id": m.sender_id,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "is_read": m.is_read,
        }
        for m in messages
    ]

    # The next_cursor is the ID of the OLDEST message in this batch (first after reverse)
    next_cursor = str(messages[0].id) if has_more and messages else None

    return {
        "messages": serialized,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }

# --- HELPER: Save Message Safely ---
def save_message_sync(appointment_id: int, user_id: int, content: str):
    """Runs in a separate thread to prevent blocking the WebSocket"""
    logger.debug("[WS] save_message_sync ENTER — appt=%s, user=%s, len=%d", appointment_id, user_id, len(content))
    db = WsSession()
    try:
        appointment = (
            db.query(Appointment)
            .filter(Appointment.id == appointment_id)
            .first()
        )
        if appointment is None or appointment.status != "confirmed":
            logger.warning(
                "[WS] Message rejected for inactive appointment %s",
                appointment_id,
            )
            return None

        new_msg = Message(
            appointment_id=appointment_id,
            sender_id=user_id,
            content=content,
            created_at=datetime.utcnow(),
            is_read=False
        )
        db.add(new_msg)
        db.commit()
        db.refresh(new_msg)
        logger.info("[WS] Message saved — id=%s", new_msg.id)
        return {
            "id": new_msg.id,
            "content": new_msg.content,
            "sender_id": new_msg.sender_id,
            "created_at": new_msg.created_at.isoformat()
        }
    except Exception as e:
        logger.error("[WS] DB Save Error: %s", e, exc_info=True)
        db.rollback()
        return None
    finally:
        db.close()


# --- HELPER: chat pushes intentionally disabled by notification policy ---
def send_chat_push_sync(appointment_id: int, sender_id: int, message_text: str):
    """
    Per-message chat notifications are intentionally disabled.

    The product notification policy reserves push notifications for major
    lifecycle events only, so live chat delivery stays inside the WebSocket.
    """
    logger.debug(
        "[WS] Chat push skipped by major-events-only policy — appt=%s sender=%s",
        appointment_id,
        sender_id,
    )


# --- WebSocket Endpoint (PRODUCTION) ---
@router.websocket("/live/{appointment_id}/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    appointment_id: int,
    user_id: int,
):
    await websocket.accept()
    auth_db = WsSession()
    try:
        auth_message = json.loads(await websocket.receive_text())
        if not isinstance(auth_message, dict) or auth_message.get("type") != "auth":
            raise HTTPException(
                status_code=401,
                detail="The first WebSocket message must authenticate the session.",
            )
        token = auth_message.get("token")
        if not isinstance(token, str) or not token:
            raise HTTPException(
                status_code=401,
                detail="A valid authentication token is required.",
            )

        current_user = deps.get_current_user(token=token, db=auth_db)
        if current_user.id != user_id:
            raise HTTPException(
                status_code=403,
                detail="Authenticated user does not match the room participant.",
            )
        require_consultation_access(
            auth_db,
            appointment_id,
            current_user,
            allow_completed=False,
        )
    except HTTPException as exc:
        logger.warning(
            "[WS] Rejected user=%s appointment=%s: %s",
            user_id,
            appointment_id,
            exc.detail,
        )
        close_code = {
            401: 4401,
            403: 4403,
            404: 4404,
            409: 4409,
            423: 4423,
        }.get(exc.status_code, 4400)
        await websocket.close(code=close_code)
        return
    except (json.JSONDecodeError, TypeError, WebSocketDisconnect):
        try:
            await websocket.close(code=4401)
        except Exception:
            pass
        return
    finally:
        auth_db.close()

    room_id = str(appointment_id)
    logger.info("[WS] Connecting: User %s to appointment %s", user_id, appointment_id)
    await manager.connect(websocket, room_id, user_id)
    
    try:
        while True:
            # 1. Receive
            data = await websocket.receive_text()
            logger.debug("[WS] Received from user %s: %s...", user_id, data[:100])
            
            # 2. Save to DB (Run in background thread!)
            logger.debug("[WS] Calling save_message_sync...")
            saved_msg = await run_in_threadpool(
                save_message_sync, 
                appointment_id,
                user_id, 
                data
            )
            logger.debug("[WS] save_message_sync returned: %s", saved_msg)

            if saved_msg:
                # 3. Broadcast the SAVED message (with real ID)
                logger.debug("[WS] Broadcasting msg id=%s...", saved_msg['id'])
                await manager.broadcast(saved_msg, room_id)
                logger.info("[WS] Broadcast complete for msg id=%s", saved_msg['id'])

                # 4. Send FCM push to the OTHER user
                logger.debug("[WS] Triggering push notification task...")
                await run_in_threadpool(
                    send_chat_push_sync,
                    appointment_id,
                    user_id,
                    data,
                )
                logger.debug("[WS] Push notification task completed")
            else:
                logger.error("[WS] save_message_sync returned None — message dropped for user %s", user_id)

    except WebSocketDisconnect:
        logger.info("[WS] Disconnected: User %s from appointment %s", user_id, appointment_id)
        await manager.disconnect(websocket, room_id, user_id)
    except Exception as e:
        logger.error("[WS] Unexpected error for user %s: %s", user_id, e, exc_info=True)
        await manager.disconnect(websocket, room_id, user_id)
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except Exception:
            pass

