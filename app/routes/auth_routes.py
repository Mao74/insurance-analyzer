from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from ..database import get_db
from .. import models, auth

router = APIRouter()

# Request/Response Models
class LoginRequest(BaseModel):
    username: str  # Can be email or username
    password: str

class LoginResponse(BaseModel):
    user_id: int
    username: str
    email: str
    is_admin: bool
    message: str

class UserResponse(BaseModel):
    user_id: int
    username: str
    email: str
    is_admin: bool

class MessageResponse(BaseModel):
    message: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

# Routes

@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    credentials: LoginRequest,
    db: Session = Depends(get_db)
):
    """Authenticate user and create session"""
    # Try to find user by email or username
    user = db.query(models.User).filter(
        (models.User.email == credentials.username) | 
        (models.User.username == credentials.username)
    ).first()
    
    if not user or not auth.verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide"
        )
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disattivato. Contatta l'amministratore."
        )
    
    # Check if access has expired
    if user.access_expires_at and user.access_expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Abbonamento scaduto"
        )
    
    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()
    
    # Set session cookie with extended info
    request.session["user"] = {
        "id": user.id, 
        "username": user.username or user.email,
        "email": user.email,
        "is_admin": user.is_admin
    }
    
    return LoginResponse(
        user_id=user.id,
        username=user.username or user.email,
        email=user.email,
        is_admin=user.is_admin,
        message="Login successful"
    )

@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request):
    """Clear session and logout user"""
    request.session.clear()
    return MessageResponse(message="Logout successful")

@router.get("/me", response_model=UserResponse)
async def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Get current authenticated user info"""
    user_data = request.session.get("user")
    
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    # Re-check user status from DB (in case it changed)
    user = db.query(models.User).filter(models.User.id == user_data["id"]).first()
    if not user:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists"
        )
    
    if not user.is_active:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disattivato"
        )
    
    if user.access_expires_at and user.access_expires_at < datetime.utcnow():
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Abbonamento scaduto"
        )
    
    return UserResponse(
        user_id=user.id,
        username=user.username or user.email,
        email=user.email,
        is_admin=user.is_admin
    )

@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db)
):
    """Change current user's password"""
    user_data = request.session.get("user")
    
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    user = db.query(models.User).filter(models.User.id == user_data["id"]).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Verify current password
    if not auth.verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password attuale non corretta"
        )
    
    # Validate new password
    if len(payload.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nuova password deve avere almeno 8 caratteri"
        )
    
    # Update password
    user.password_hash = auth.get_password_hash(payload.new_password)
    db.commit()
    
    return MessageResponse(message="Password aggiornata con successo")

