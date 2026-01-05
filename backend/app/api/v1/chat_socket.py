from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from typing import List, Dict
from app.core.database import get_db, SessionLocal # <--- Import SessionLocal
from app.models.message import Message
import json
from datetime import datetime

router = APIRouter()

# --- 1. Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, appointment_id: str):
        await websocket.accept()
        if appointment_id not in self.active_connections:
            self.active_connections[appointment_id] = []
        self.active_connections[appointment_id].append(websocket)

    def disconnect(self, websocket: WebSocket, appointment_id: str):
        if appointment_id in self.active_connections:
            if websocket in self.active_connections[appointment_id]:
                self.active_connections[appointment_id].remove(websocket)
            if not self.active_connections[appointment_id]:
                del self.active_connections[appointment_id]

    async def broadcast(self, message: dict, appointment_id: str):
        if appointment_id in self.active_connections:
            # Iterate over a copy to avoid modification errors
            for connection in self.active_connections[appointment_id][:]:
                try:
                    await connection.send_text(json.dumps(message))
                except Exception:
                    # Remove dead connections
                    self.disconnect(connection, appointment_id)

manager = ConnectionManager()

# --- 2. History Endpoint (HTTP - Keep get_db here) ---
@router.get("/history/{appointment_id}")
def get_chat_history(appointment_id: int, db: Session = Depends(get_db)):
    messages = db.query(Message).filter(Message.appointment_id == appointment_id).order_by(Message.created_at.asc()).all()
    return messages

# --- 3. The WebSocket Endpoint (MANUAL SESSION) ---
@router.websocket("/ws/{appointment_id}/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    appointment_id: str, 
    user_id: int
    # REMOVED: db: Session = Depends(get_db) <--- This was likely the silent killer
):
    await manager.connect(websocket, appointment_id)
    try:
        while True:
            # 1. Wait for message
            data = await websocket.receive_text()
            
            # 2. Open DB Session Manually
            db = SessionLocal()
            try:
                # 3. Save to DB
                new_msg = Message(
                    appointment_id=int(appointment_id),
                    sender_id=user_id,
                    content=data,
                    created_at=datetime.utcnow(),
                    is_read=False
                )
                db.add(new_msg)
                db.commit()
                db.refresh(new_msg)

                # 4. Prepare Response
                response_data = {
                    "id": new_msg.id,
                    "content": new_msg.content,
                    "sender_id": new_msg.sender_id,
                    "created_at": new_msg.created_at.isoformat()
                }
            except Exception as e:
                print(f"DB Error: {e}")
                continue
            finally:
                db.close() # Always close session!

            # 5. Broadcast
            await manager.broadcast(response_data, appointment_id)

    except WebSocketDisconnect:
        manager.disconnect(websocket, appointment_id)
    except Exception as e:
        print(f"WebSocket Error: {e}")
        manager.disconnect(websocket, appointment_id)