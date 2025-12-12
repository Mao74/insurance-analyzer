from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from .. import models, auth

router = APIRouter()

# Request/Response Models
class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    user_id: int
    username: str
    message: str

class UserResponse(BaseModel):
    user_id: int
    username: str

class MessageResponse(BaseModel):
    message: str

# Routes

@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    credentials: LoginRequest,
    db: Session = Depends(get_db)
):
    """Authenticate user and create session"""
    user = db.query(models.User).filter(models.User.username == credentials.username).first()
    
    if not user or not auth.verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    # Set session cookie
    request.session["user"] = {"id": user.id, "username": user.username}
    
    return LoginResponse(
        user_id=user.id,
        username=user.username,
        message="Login successful"
    )

@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request):
    """Clear session and logout user"""
    request.session.clear()
    return MessageResponse(message="Logout successful")

@router.get("/me", response_model=UserResponse)
async def get_current_user(request: Request):
    """Get current authenticated user info"""
    user_data = request.session.get("user")
    
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    return UserResponse(
        user_id=user_data["id"],
        username=user_data["username"]
    )
