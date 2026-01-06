from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from typing import List, Dict
import json
from datetime import datetime

# DB Imports (We keep them for history, but won't use them in WS for now)
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

# --- 🧪 DIAGNOSTIC ENDPOINT ---
@router.get("/test")
def chat_test():
    return {"status": "ok", "message": "Chat Router is Online"}

# --- History Endpoint (This works, so we keep it) ---
@router.get("/history/{appointment_id}")
def get_chat_history(appointment_id: int, db: Session = Depends(get_db)):
    return db.query(Message).filter(Message.appointment_id == appointment_id).order_by(Message.created_at.asc()).all()

# --- WebSocket Endpoint (SAFE MODE) ---
@router.websocket("/live/{appointment_id}/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    appointment_id: str, 
    user_id: int
):
    print(f"✅ WS Connecting: User {user_id}")
    await manager.connect(websocket, appointment_id)
    
    # Send a welcome message to prove connection worked
    await manager.broadcast({
        "id": 0,
        "content": "SYSTEM: Connected (Database Saving Disabled)",
        "sender_id": 0, 
        "created_at": str(datetime.now())
    }, appointment_id)

    try:
        while True:
            data = await websocket.receive_text()
            
            # --- DATABASE BLOCK (DISABLED FOR DIAGNOSTICS) ---
            # If the app connects now, we know the DB code below was the crasher.
            '''
            db = Session(bind=engine)
            try:
                new_msg = Message(appointment_id=int(appointment_id), sender_id=user_id, content=data, created_at=datetime.utcnow(), is_read=False)
                db.add(new_msg)
                db.commit()
                db.refresh(new_msg)
            except Exception as e:
                print(f"DB Error: {e}")
            finally:
                db.close()
            '''
            # -------------------------------------------------

            # Just Broadcast (Echo)
            response_data = {
                "id": 0, # Dummy ID
                "content": data,
                "sender_id": user_id,
                "created_at": str(datetime.now())
            }

            await manager.broadcast(response_data, appointment_id)

    except WebSocketDisconnect:
        manager.disconnect(websocket, appointment_id)
        print(f"🔌 Disconnected: User {user_id}")