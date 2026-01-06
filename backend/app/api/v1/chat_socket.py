from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List, Dict
import json
from datetime import datetime

# 1. Import 'engine' directly (We KNOW this exists because main.py uses it)
from app.core.database import engine
from sqlalchemy.orm import sessionmaker
from app.models.message import Message

# 2. Create our own Session Maker locally
# This replaces 'SessionLocal' and guarantees we have a working DB builder
WsSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# For the history endpoint only
from fastapi import Depends
from sqlalchemy.orm import Session
from app.core.database import get_db

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

# --- HTTP History Endpoint ---
@router.get("/history/{appointment_id}")
def get_chat_history(appointment_id: int, db: Session = Depends(get_db)):
    # This works because get_db is standard, but the WebSocket needs special care
    return db.query(Message).filter(Message.appointment_id == appointment_id).order_by(Message.created_at.asc()).all()

# --- WebSocket Endpoint ---
@router.websocket("/live/{appointment_id}/{user_id}") 
async def websocket_endpoint(
    websocket: WebSocket, 
    appointment_id: str, 
    user_id: int
):
    await manager.connect(websocket, appointment_id)
    try:
        while True:
            # 1. Receive
            data = await websocket.receive_text()
            
            # 2. Open Session directly from Engine (Safe!)
            # We use the WsSession we created at the top of the file
            db = WsSession()
            try:
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
                db.close() 

            # 3. Broadcast
            await manager.broadcast(response_data, appointment_id)

    except WebSocketDisconnect:
        manager.disconnect(websocket, appointment_id)
    except Exception as e:
        print(f"WebSocket Error: {e}")
        manager.disconnect(websocket, appointment_id)