from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
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
from app.models.doctor import Doctor
from app.models.user import User
from app.core.notifications import send_push_notification

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
        await websocket.accept()
        if appointment_id not in self.active_connections:
            self.active_connections[appointment_id] = []
            self.connected_users[appointment_id] = set()
        self.active_connections[appointment_id].append(websocket)
        self.connected_users[appointment_id].add(user_id)

    def disconnect(self, websocket: WebSocket, appointment_id: str, user_id: int):
        if appointment_id in self.active_connections:
            if websocket in self.active_connections[appointment_id]:
                self.active_connections[appointment_id].remove(websocket)
            self.connected_users[appointment_id].discard(user_id)
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
                    print(f"DEBUG BROADCAST: send failed, removing dead socket: {e}", flush=True)
                    logger.warning(f"[WS] Broadcast send failed, removing dead socket: {e}")
                    self.disconnect(connection, appointment_id, 0)

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
    cursor: Optional[str] = Query(None, description="ID of the last message from the previous page"),
    limit: int = Query(20, ge=1, le=100, description="Number of messages per page"),
):
    query = db.query(Message).filter(Message.appointment_id == appointment_id)

    # If cursor is provided, find the cursor message's timestamp and filter older messages
    if cursor is not None:
        cursor_message = db.query(Message).filter(Message.id == int(cursor)).first()
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
    print(f"DEBUG DB-SAVE: ENTER — appt={appointment_id}, user={user_id}, len={len(content)}", flush=True)
    logger.info(f"[WS] save_message_sync called — appt={appointment_id}, user={user_id}, len={len(content)}")
    db = WsSession()
    try:
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
        print(f"DEBUG DB-SAVE: SUCCESS — msg id={new_msg.id}", flush=True)
        logger.info(f"[WS] Message saved — id={new_msg.id}")
        return {
            "id": new_msg.id,
            "content": new_msg.content,
            "sender_id": new_msg.sender_id,
            "created_at": new_msg.created_at.isoformat()
        }
    except Exception as e:
        print(f"DEBUG DB-SAVE: FAILED — {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        logger.error(f"[WS] DB Save Error: {e}\n{traceback.format_exc()}")
        db.rollback()
        return None
    finally:
        db.close()


# --- HELPER: Look up recipient and send FCM push ---
def send_chat_push_sync(appointment_id: int, sender_id: int, message_text: str):
    """
    Determine the recipient of a chat message and fire an FCM push.
    Runs in a threadpool so it doesn't block the WebSocket loop.
    """
    print(f"DEBUG FCM: ENTER — appt={appointment_id}, sender={sender_id}", flush=True)
    logger.info(f"[FCM-PUSH] Starting push lookup — appt={appointment_id}, sender={sender_id}")
    db = WsSession()
    try:
        appointment = (
            db.query(Appointment)
            .filter(Appointment.id == appointment_id)
            .first()
        )
        if not appointment:
            print(f"DEBUG FCM: No appointment found for id={appointment_id}", flush=True)
            logger.warning(f"[FCM-PUSH] No appointment found for id={appointment_id}")
            return

        print(f"DEBUG FCM: Appointment found — patient_id={appointment.patient_id}, doctor_id={appointment.doctor_id}", flush=True)

        # Determine the recipient's User ID
        if sender_id == appointment.patient_id:
            doctor = (
                db.query(Doctor)
                .filter(Doctor.id == appointment.doctor_id)
                .first()
            )
            if not doctor:
                print(f"DEBUG FCM: No doctor found for doctor_id={appointment.doctor_id}", flush=True)
                logger.warning(f"[FCM-PUSH] No doctor found for doctor_id={appointment.doctor_id}")
                return
            recipient_user_id = doctor.user_id
            sender_label = "Patient"
        else:
            recipient_user_id = appointment.patient_id
            sender_label = "Doctor"

        print(f"DEBUG FCM: Recipient user_id={recipient_user_id}, sender_label={sender_label}", flush=True)

        recipient = db.query(User).filter(User.id == recipient_user_id).first()
        sender = db.query(User).filter(User.id == sender_id).first()

        if not recipient:
            print(f"DEBUG FCM: Recipient user NOT FOUND — user_id={recipient_user_id}", flush=True)
            logger.warning(f"[FCM-PUSH] Recipient user not found — user_id={recipient_user_id}")
            return

        if not recipient.fcm_token:
            print(f"DEBUG FCM: Recipient user_id={recipient_user_id} has NO FCM TOKEN — skipping", flush=True)
            logger.info(f"[FCM-PUSH] Recipient user_id={recipient_user_id} has no FCM token — skipping push")
            return

        sender_name = f"{sender.first_name} {sender.last_name}" if sender else sender_label
        body_preview = message_text[:200] + "…" if len(message_text) > 200 else message_text

        print(f"DEBUG FCM: SENDING push to user_id={recipient_user_id} token={recipient.fcm_token[:12]}...", flush=True)
        logger.info(f"[FCM-PUSH] Sending push to user_id={recipient_user_id} (token={recipient.fcm_token[:12]}...)")

        result = send_push_notification(
            token=recipient.fcm_token,
            title=f"New message from {sender_name}",
            body=body_preview,
            data={
                "type": "chat_message",
                "appointment_id": str(appointment_id),
                "sender_id": str(sender_id),
            },
        )
        print(f"DEBUG FCM: send_push_notification returned: {result}", flush=True)
    except Exception as e:
        print(f"DEBUG FCM: EXCEPTION — {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        logger.error(f"[FCM-PUSH] Error: {e}\n{traceback.format_exc()}")
    finally:
        db.close()


# --- WebSocket Endpoint (PRODUCTION) ---
@router.websocket("/live/{appointment_id}/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    appointment_id: str, 
    user_id: int
):
    print(f"DEBUG WS: CONNECT — User {user_id}, Appointment {appointment_id}", flush=True)
    logger.info(f"[WS] Connecting: User {user_id} to appointment {appointment_id}")
    await manager.connect(websocket, appointment_id, user_id)
    
    try:
        while True:
            # 1. Receive
            data = await websocket.receive_text()
            print(f"DEBUG WS: RECEIVED from user {user_id} — {data[:100]}", flush=True)
            logger.info(f"[WS] Received from user {user_id}: {data[:80]}...")
            
            # 2. Save to DB (Run in background thread!)
            print(f"DEBUG WS: Calling save_message_sync...", flush=True)
            saved_msg = await run_in_threadpool(
                save_message_sync, 
                int(appointment_id), 
                user_id, 
                data
            )
            print(f"DEBUG WS: save_message_sync returned: {saved_msg}", flush=True)

            if saved_msg:
                # 3. Broadcast the SAVED message (with real ID)
                print(f"DEBUG WS: Broadcasting msg id={saved_msg['id']}...", flush=True)
                await manager.broadcast(saved_msg, appointment_id)
                print(f"DEBUG WS: Broadcast DONE for msg id={saved_msg['id']}", flush=True)
                logger.info(f"[WS] Broadcast complete for msg id={saved_msg['id']}")

                # 4. Send FCM push to the OTHER user
                print(f"DEBUG WS: Triggering push notification task...", flush=True)
                await run_in_threadpool(
                    send_chat_push_sync,
                    int(appointment_id),
                    user_id,
                    data,
                )
                print(f"DEBUG WS: Push notification task completed", flush=True)
            else:
                print(f"DEBUG WS: save_message_sync returned None — MESSAGE DROPPED", flush=True)
                logger.error(f"[WS] save_message_sync returned None — message dropped for user {user_id}")

    except WebSocketDisconnect:
        print(f"DEBUG WS: DISCONNECT — User {user_id}", flush=True)
        manager.disconnect(websocket, appointment_id, user_id)
        logger.info(f"[WS] Disconnected: User {user_id} from appointment {appointment_id}")
    except Exception as e:
        print(f"DEBUG WS: UNEXPECTED EXCEPTION — {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        logger.error(f"[WS] Unexpected error for user {user_id}: {e}\n{traceback.format_exc()}")
        manager.disconnect(websocket, appointment_id, user_id)
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except Exception:
            pass
