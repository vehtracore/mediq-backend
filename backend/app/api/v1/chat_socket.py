from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from typing import List, Dict
import json
from datetime import datetime

# Keep these imports so the file doesn't break, but we WON'T use them in the socket
from app.core.database import engine, get_db
from sqlalchemy.orm import sessionmaker, Session
from app.models.message import Message

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

# --- 🧪 DIAGNOSTIC ENDPOINT (Keep this!) ---
@router.get("/test")
def chat_test():
    return {"status": "ok", "message": "Chat Router is Online"}

# --- History Endpoint (HTTP works fine) ---
@router.get("/history/{appointment_id}")
def get_chat_history(appointment_id: int, db: Session = Depends(get_db)):
    return db.query(Message).filter(Message.appointment_id == appointment_id).order_by(Message.created_at.asc()).all()

# --- WebSocket Endpoint (PURE ECHO MODE) ---
@router.websocket("/live/{appointment_id}/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    appointment_id: str, 
    user_id: int
):
    print(f"✅ WS Connecting: User {user_id}")
    await manager.connect(websocket, appointment_id)
    
    # 1. Send Immediate Welcome Message
    # If you see this, the connection is solid.
    await manager.broadcast({
        "id": 0,
        "content": "SYSTEM: Connected! (DB Saving Disabled)",
        "sender_id": 0, 
        "created_at": str(datetime.now())
    }, appointment_id)

    try:
        while True:
            # 2. Receive Message
            data = await websocket.receive_text()
            
            # --- 🛑 DATABASE SAVING REMOVED 🛑 ---
            # We are NOT saving to DB here. This isolates the crash.
            
            # 3. Echo it back
            response_data = {
                "id": 0, 
                "content": f"Echo: {data}",
                "sender_id": user_id,
                "created_at": str(datetime.now())
            }

            await manager.broadcast(response_data, appointment_id)

    except WebSocketDisconnect:
        manager.disconnect(websocket, appointment_id)
        print(f"🔌 Disconnected: User {user_id}")