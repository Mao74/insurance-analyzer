from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime, timedelta
import secrets
from ..database import get_db
from .. import models, auth

router = APIRouter()

# Rate limiting settings
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15

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

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


# Routes

@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    credentials: LoginRequest,
    db: Session = Depends(get_db)
):
    """Authenticate user and create session with rate limiting"""
    # Try to find user by email or username
    user = db.query(models.User).filter(
        (models.User.email == credentials.username) | 
        (models.User.username == credentials.username)
    ).first()
    
    # Check if account is locked (rate limiting)
    if user and user.locked_until and user.locked_until > datetime.utcnow():
        remaining_seconds = (user.locked_until - datetime.utcnow()).total_seconds()
        remaining_minutes = int(remaining_seconds / 60) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account bloccato per troppi tentativi. Riprova tra {remaining_minutes} minuti."
        )
    
    if not user or not auth.verify_password(credentials.password, user.password_hash):
        # Increment login attempts for existing user
        if user:
            user.login_attempts = (user.login_attempts or 0) + 1
            
            # Lock account if max attempts reached
            if user.login_attempts >= MAX_LOGIN_ATTEMPTS:
                user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Account bloccato per troppi tentativi. Riprova tra {LOCKOUT_DURATION_MINUTES} minuti."
                )
            
            db.commit()
            remaining_attempts = MAX_LOGIN_ATTEMPTS - user.login_attempts
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Credenziali non valide. {remaining_attempts} tentativi rimasti."
            )
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide"
        )
    
    # Successful login - reset login attempts
    user.login_attempts = 0
    user.locked_until = None
    
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


# Password Reset Routes

@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db)
):
    """Request password reset - generates token and sends email"""
    from ..email_service import send_password_reset_email
    
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    
    # Always return success to prevent email enumeration attacks
    if not user:
        return MessageResponse(message="Se l'email esiste nel sistema, riceverai le istruzioni per il reset.")
    
    # Invalidate any existing tokens for this user
    db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.user_id == user.id,
        models.PasswordResetToken.used == False
    ).update({"used": True})
    
    # Generate new token (URL-safe, 32 bytes = 43 chars base64)
    token = secrets.token_urlsafe(32)
    
    # Token expires in 1 hour
    reset_token = models.PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=1)
    )
    db.add(reset_token)
    db.commit()
    
    # Send email via Resend
    email_sent = send_password_reset_email(
        to_email=user.email,
        reset_token=token,
        user_name=user.username
    )
    
    if email_sent:
        print(f"[AUTH] Password reset email sent to {user.email}")
    else:
        # Email not sent (Resend not configured), log token for debugging
        print(f"[AUTH] PASSWORD RESET for {user.email} - Token: {token}")
    
    return MessageResponse(
        message="Se l'email esiste nel sistema, riceverai le istruzioni per il reset."
    )

@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db)
):
    """Reset password using token from forgot-password email"""
    # Find the token
    reset_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token == payload.token,
        models.PasswordResetToken.used == False
    ).first()
    
    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token non valido o già utilizzato"
        )
    
    # Check if token has expired
    if reset_token.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token scaduto. Richiedi un nuovo reset password."
        )
    
    # Validate new password
    if len(payload.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nuova password deve avere almeno 8 caratteri"
        )
    
    # Get user and update password
    user = db.query(models.User).filter(models.User.id == reset_token.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utente non trovato"
        )
    
    # Update password
    user.password_hash = auth.get_password_hash(payload.new_password)
    
    # Reset login attempts and unlock account
    user.login_attempts = 0
    user.locked_until = None
    
    # Mark token as used
    reset_token.used = True
    
    db.commit()
    
    return MessageResponse(message="Password reimpostata con successo. Ora puoi effettuare il login.")
