from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.concurrency import run_in_threadpool # <--- THE SECRET WEAPON
from typing import List, Dict
import json
from datetime import datetime

# 1. DB Imports
from app.core.database import engine, get_db
from sqlalchemy.orm import sessionmaker, Session
from app.models.message import Message

# Create local session maker
WsSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

router = APIRouter()

# --- Connection Manager ---
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
            for connection in self.active_connections[appointment_id][:]:
                try:
                    await connection.send_text(json.dumps(message))
                except Exception:
                    self.disconnect(connection, appointment_id)

manager = ConnectionManager()

# --- 🧪 DIAGNOSTIC ENDPOINT ---
@router.get("/test")
def chat_test():
    return {"status": "ok", "message": "Chat Router is Online"}

# --- History Endpoint ---
@router.get("/history/{appointment_id}")
def get_chat_history(appointment_id: int, db: Session = Depends(get_db)):
    return db.query(Message).filter(Message.appointment_id == appointment_id).order_by(Message.created_at.asc()).all()

# --- HELPER: Save Message Safely ---
def save_message_sync(appointment_id: int, user_id: int, content: str):
    """Runs in a separate thread to prevent blocking the WebSocket"""
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
        return {
            "id": new_msg.id,
            "content": new_msg.content,
            "sender_id": new_msg.sender_id,
            "created_at": new_msg.created_at.isoformat()
        }
    except Exception as e:
        print(f"❌ DB Save Error: {e}")
        return None
    finally:
        db.close()

# --- WebSocket Endpoint (PRODUCTION) ---
@router.websocket("/live/{appointment_id}/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    appointment_id: str, 
    user_id: int
):
    print(f"✅ WS Connecting: User {user_id}")
    await manager.connect(websocket, appointment_id)
    
    try:
        while True:
            # 1. Receive
            data = await websocket.receive_text()
            
            # 2. Save to DB (Run in background thread!)
            saved_msg = await run_in_threadpool(
                save_message_sync, 
                int(appointment_id), 
                user_id, 
                data
            )

            if saved_msg:
                # 3. Broadcast the SAVED message (with real ID)
                await manager.broadcast(saved_msg, appointment_id)

    except WebSocketDisconnect:
        manager.disconnect(websocket, appointment_id)
        print(f"🔌 Disconnected: User {user_id}")