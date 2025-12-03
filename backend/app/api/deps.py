from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core import security
from app.models.user import User

# Points to the endpoint where the client gets the token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # DEBUG LOGS
        print(f"🕵️‍♂️ [DEBUG] Token received: {token[:10]}...") 
        
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        
        email: str = payload.get("sub")
        if email is None:
            print("❌ [DEBUG] No 'sub' (email) in token.")
            raise credentials_exception
            
    except JWTError as e:
        print(f"❌ [DEBUG] JWT Decode Error: {e}")
        raise credentials_exception
        
    # Fetch User from DB
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        print(f"❌ [DEBUG] User {email} not found in Database.")
        raise credentials_exception
        
    # FIXED LINE BELOW: Changed .full_name to .first_name
    print(f"✅ [DEBUG] User authenticated: {user.first_name}")
    return user