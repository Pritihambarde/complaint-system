import os, bcrypt, jwt
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from .database import get_db
from . import models

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")

def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

def verify_password(p: str, h: str) -> bool:
    return bcrypt.checkpw(p.encode(), h.encode())

def create_token(user_id: int, role: str, minutes: int = 60, act_by: int = None) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    claims = {"sub": str(user_id), "role": role, "exp": exp}
    if act_by:
        claims["act_by"] = act_by          # admin who is viewing this account (audit trail)
    return jwt.encode(claims, SECRET_KEY, algorithm="HS256")

def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> models.User:
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(models.User, int(data["sub"]))
    if not user:
        raise HTTPException(401, "User not found")
    if user.is_active is False:
        raise HTTPException(401, "This account has been disabled by the admin")
    return user

def require_role(*roles):
    def checker(user: models.User = Depends(current_user)):
        if user.role not in roles:
            raise HTTPException(403, "You do not have permission for this action")
        return user
    return checker
