"""Admin routes for user management"""

from fastapi import APIRouter, Request, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date
from decimal import Decimal
from ..database import get_db
from .. import models, auth

router = APIRouter()

# Helper to check admin access
def require_admin(request: Request, db: Session):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if not user_data.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    return user_data

# Pydantic Models
class UserCreate(BaseModel):
    email: str
    password: str
    is_admin: bool = False
    access_expires_at: Optional[datetime] = None

class UserUpdate(BaseModel):
    email: Optional[str] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    access_expires_at: Optional[datetime] = None
    reset_password: Optional[str] = None

class UserListItem(BaseModel):
    id: int
    email: str
    username: Optional[str]
    is_admin: bool
    is_active: bool
    access_expires_at: Optional[datetime]
    last_login: Optional[datetime]
    total_tokens_used: int
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    created_at: datetime

class UserListResponse(BaseModel):
    users: List[UserListItem]
    total: int

# Routes

@router.get("/users", response_model=UserListResponse)
async def list_users(
    request: Request,
    db: Session = Depends(get_db)
):
    """List all users (admin only)"""
    require_admin(request, db)
    
    users = db.query(models.User).order_by(models.User.created_at.desc()).all()
    
    return UserListResponse(
        users=[
            UserListItem(
                id=u.id,
                email=u.email,
                username=u.username,
                is_admin=u.is_admin or False,
                is_active=u.is_active if u.is_active is not None else True,
                access_expires_at=u.access_expires_at,
                last_login=u.last_login,
                total_tokens_used=u.total_tokens_used or 0,
                total_input_tokens=u.total_input_tokens or 0,
                total_output_tokens=u.total_output_tokens or 0,
                created_at=u.created_at
            )
            for u in users
        ],
        total=len(users)
    )

@router.post("/users", response_model=UserListItem)
async def create_user(
    request: Request,
    payload: UserCreate,
    db: Session = Depends(get_db)
):
    """Create a new user (admin only)"""
    require_admin(request, db)
    
    # Check if email already exists
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email già registrata"
        )
    
    # Validate password
    if len(payload.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La password deve avere almeno 8 caratteri"
        )
    
    # Create user
    user = models.User(
        email=payload.email,
        username=payload.email,  # Use email as username
        password_hash=auth.get_password_hash(payload.password),
        is_admin=payload.is_admin,
        is_active=True,
        access_expires_at=payload.access_expires_at
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Send welcome email
    from ..email_service import send_welcome_email
    email_sent = send_welcome_email(to_email=user.email, user_name=user.username)
    if email_sent:
        print(f"[ADMIN] Welcome email sent to {user.email}")
    
    return UserListItem(
        id=user.id,
        email=user.email,
        username=user.username,
        is_admin=user.is_admin or False,
        is_active=user.is_active if user.is_active is not None else True,
        access_expires_at=user.access_expires_at,
        last_login=user.last_login,
        total_tokens_used=user.total_tokens_used or 0,
        total_input_tokens=user.total_input_tokens or 0,
        total_output_tokens=user.total_output_tokens or 0,
        created_at=user.created_at
    )

@router.put("/users/{user_id}", response_model=UserListItem)
async def update_user(
    user_id: int,
    request: Request,
    payload: UserUpdate,
    db: Session = Depends(get_db)
):
    """Update a user (admin only)"""
    require_admin(request, db)
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    
    # Update fields if provided
    if payload.email is not None:
        # Check if email is taken by another user
        existing = db.query(models.User).filter(
            models.User.email == payload.email,
            models.User.id != user_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email già in uso")
        user.email = payload.email
    
    if payload.is_active is not None:
        user.is_active = payload.is_active
    
    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    
    if payload.access_expires_at is not None:
        user.access_expires_at = payload.access_expires_at
    
    if payload.reset_password:
        if len(payload.reset_password) < 8:
            raise HTTPException(status_code=400, detail="La password deve avere almeno 8 caratteri")
        user.password_hash = auth.get_password_hash(payload.reset_password)
    
    db.commit()
    db.refresh(user)
    
    return UserListItem(
        id=user.id,
        email=user.email,
        username=user.username,
        is_admin=user.is_admin or False,
        is_active=user.is_active if user.is_active is not None else True,
        access_expires_at=user.access_expires_at,
        last_login=user.last_login,
        total_tokens_used=user.total_tokens_used or 0,
        total_input_tokens=user.total_input_tokens or 0,
        total_output_tokens=user.total_output_tokens or 0,
        created_at=user.created_at
    )

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Delete a user (admin only)"""
    admin_data = require_admin(request, db)
    
    # Prevent self-deletion
    if user_id == admin_data["id"]:
        raise HTTPException(status_code=400, detail="Non puoi eliminare il tuo account")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    
    db.delete(user)
    db.commit()
    
    return {"message": "Utente eliminato"}


# System Settings Routes

class SettingsResponse(BaseModel):
    llm_model_name: str
    input_cost_per_million: str
    output_cost_per_million: str

class SettingsUpdate(BaseModel):
    llm_model_name: Optional[str] = None
    input_cost_per_million: Optional[str] = None
    output_cost_per_million: Optional[str] = None

@router.get("/settings", response_model=SettingsResponse)
async def get_settings(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get system settings (admin only)"""
    require_admin(request, db)
    
    # Get or create singleton settings
    settings = db.query(models.SystemSettings).first()
    if not settings:
        settings = models.SystemSettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    
    return SettingsResponse(
        llm_model_name=settings.llm_model_name,
        input_cost_per_million=settings.input_cost_per_million,
        output_cost_per_million=settings.output_cost_per_million
    )

@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    request: Request,
    payload: SettingsUpdate,
    db: Session = Depends(get_db)
):
    """Update system settings (admin only)"""
    require_admin(request, db)
    
    # Get or create singleton settings
    settings = db.query(models.SystemSettings).first()
    if not settings:
        settings = models.SystemSettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    
    # Update fields if provided
    if payload.llm_model_name is not None:
        settings.llm_model_name = payload.llm_model_name
    if payload.input_cost_per_million is not None:
        settings.input_cost_per_million = payload.input_cost_per_million
    if payload.output_cost_per_million is not None:
        settings.output_cost_per_million = payload.output_cost_per_million

    db.commit()
    db.refresh(settings)

    return SettingsResponse(
        llm_model_name=settings.llm_model_name,
        input_cost_per_million=settings.input_cost_per_million,
        output_cost_per_million=settings.output_cost_per_million
    )


# Analytics Routes

class DailyCostData(BaseModel):
    date: str  # YYYY-MM-DD format
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float

class MonthlyCostData(BaseModel):
    month: str  # YYYY-MM format
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float

class CostAnalyticsResponse(BaseModel):
    today: DailyCostData
    this_month: MonthlyCostData
    total: DailyCostData  # All time
    monthly_data: List[MonthlyCostData]  # Last 12 months

@router.get("/analytics/costs", response_model=CostAnalyticsResponse)
async def get_cost_analytics(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get token usage and cost analytics (admin only)"""
    require_admin(request, db)

    # Get system settings for cost calculation
    settings = db.query(models.SystemSettings).first()
    if not settings:
        settings = models.SystemSettings()

    input_cost_per_million = float(settings.input_cost_per_million)
    output_cost_per_million = float(settings.output_cost_per_million)

    def calculate_cost(input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD"""
        input_cost = (input_tokens / 1_000_000) * input_cost_per_million
        output_cost = (output_tokens / 1_000_000) * output_cost_per_million
        return round(input_cost + output_cost, 4)

    # Get today's date
    today = date.today()

    # Query for today's data
    today_data = db.query(
        func.coalesce(func.sum(models.Analysis.input_tokens), 0).label('input_tokens'),
        func.coalesce(func.sum(models.Analysis.output_tokens), 0).label('output_tokens')
    ).filter(
        func.date(models.Analysis.created_at) == today,
        models.Analysis.status == models.AnalysisStatus.COMPLETED
    ).first()

    today_input = int(today_data.input_tokens) if today_data else 0
    today_output = int(today_data.output_tokens) if today_data else 0

    # Query for this month's data
    this_month_start = today.replace(day=1)
    this_month_data = db.query(
        func.coalesce(func.sum(models.Analysis.input_tokens), 0).label('input_tokens'),
        func.coalesce(func.sum(models.Analysis.output_tokens), 0).label('output_tokens')
    ).filter(
        func.date(models.Analysis.created_at) >= this_month_start,
        models.Analysis.status == models.AnalysisStatus.COMPLETED
    ).first()

    month_input = int(this_month_data.input_tokens) if this_month_data else 0
    month_output = int(this_month_data.output_tokens) if this_month_data else 0

    # Query for all-time data
    total_data = db.query(
        func.coalesce(func.sum(models.Analysis.input_tokens), 0).label('input_tokens'),
        func.coalesce(func.sum(models.Analysis.output_tokens), 0).label('output_tokens')
    ).filter(
        models.Analysis.status == models.AnalysisStatus.COMPLETED
    ).first()

    total_input = int(total_data.input_tokens) if total_data else 0
    total_output = int(total_data.output_tokens) if total_data else 0

    # Query for monthly breakdown (last 12 months)
    monthly_data = db.query(
        func.date_trunc('month', models.Analysis.created_at).label('month'),
        func.coalesce(func.sum(models.Analysis.input_tokens), 0).label('input_tokens'),
        func.coalesce(func.sum(models.Analysis.output_tokens), 0).label('output_tokens')
    ).filter(
        models.Analysis.status == models.AnalysisStatus.COMPLETED,
        models.Analysis.created_at.isnot(None)
    ).group_by(
        func.date_trunc('month', models.Analysis.created_at)
    ).order_by(
        func.date_trunc('month', models.Analysis.created_at).desc()
    ).limit(12).all()

    monthly_list = []
    for row in monthly_data:
        month_date = row.month
        month_str = month_date.strftime('%Y-%m') if month_date else ''
        m_input = int(row.input_tokens)
        m_output = int(row.output_tokens)
        monthly_list.append(MonthlyCostData(
            month=month_str,
            input_tokens=m_input,
            output_tokens=m_output,
            total_tokens=m_input + m_output,
            cost=calculate_cost(m_input, m_output)
        ))

    # Reverse to get chronological order
    monthly_list.reverse()

    return CostAnalyticsResponse(
        today=DailyCostData(
            date=today.isoformat(),
            input_tokens=today_input,
            output_tokens=today_output,
            total_tokens=today_input + today_output,
            cost=calculate_cost(today_input, today_output)
        ),
        this_month=MonthlyCostData(
            month=today.strftime('%Y-%m'),
            input_tokens=month_input,
            output_tokens=month_output,
            total_tokens=month_input + month_output,
            cost=calculate_cost(month_input, month_output)
        ),
        total=DailyCostData(
            date='all-time',
            input_tokens=total_input,
            output_tokens=total_output,
            total_tokens=total_input + total_output,
            cost=calculate_cost(total_input, total_output)
        ),
        monthly_data=monthly_list
    )
