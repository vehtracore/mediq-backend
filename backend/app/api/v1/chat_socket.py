from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict
from app.core.database import get_db
from app.models.message import Message
from app.models.user import User
from app.core.security import get_current_user_ws # We need a special auth for WebSockets
import json
from datetime import datetime

router = APIRouter()

# --- 1. Connection Manager ---
class ConnectionManager:
    def __init__(self):
        # Dictionary to hold active connections: {appointment_id: [socket1, socket2]}
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, appointment_id: str):
        await websocket.accept()
        if appointment_id not in self.active_connections:
            self.active_connections[appointment_id] = []
        self.active_connections[appointment_id].append(websocket)

    def disconnect(self, websocket: WebSocket, appointment_id: str):
        if appointment_id in self.active_connections:
            self.active_connections[appointment_id].remove(websocket)
            if not self.active_connections[appointment_id]:
                del self.active_connections[appointment_id]

    async def broadcast(self, message: dict, appointment_id: str):
        if appointment_id in self.active_connections:
            for connection in self.active_connections[appointment_id]:
                await connection.send_text(json.dumps(message))

manager = ConnectionManager()

# --- 2. History Endpoint (Load previous messages) ---
@router.get("/history/{appointment_id}")
def get_chat_history(appointment_id: int, db: Session = Depends(get_db)):
    messages = db.query(Message).filter(Message.appointment_id == appointment_id).order_by(Message.created_at.asc()).all()
    return messages

# --- 3. The WebSocket Endpoint ---
@router.websocket("/ws/{appointment_id}/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    appointment_id: str, 
    user_id: int,
    db: Session = Depends(get_db)
):
    await manager.connect(websocket, appointment_id)
    try:
        while True:
            # Wait for data from the client
            data = await websocket.receive_text()
            
            # Save to Database
            new_msg = Message(
                appointment_id=int(appointment_id),
                sender_id=user_id,
                content=data,
                created_at=datetime.utcnow()
            )
            db.add(new_msg)
            db.commit()
            db.refresh(new_msg)

            # Construct the JSON message to send back
            response_data = {
                "id": new_msg.id,
                "content": new_msg.content,
                "sender_id": new_msg.sender_id,
                "created_at": new_msg.created_at.isoformat()
            }

            # Broadcast to everyone in this appointment room
            await manager.broadcast(response_data, appointment_id)

    except WebSocketDisconnect:
        manager.disconnect(websocket, appointment_id)
    except Exception as e:
        print(f"WebSocket Error: {e}")
        manager.disconnect(websocket, appointment_id)