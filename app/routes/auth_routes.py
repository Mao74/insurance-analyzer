from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, auth
from ..config import settings
from typing import Optional

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = request.session.get("user")
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/login", status_code=303)

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not auth.verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Credenziali non valide"})
    
    # Set session
    request.session["user"] = {"id": user.id, "username": user.username}
    return RedirectResponse(url="/dashboard", status_code=303)

@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data:
        return RedirectResponse(url="/login", status_code=303)
    
    # Get Saved Analyses (Archived)
    saved_analyses = db.query(models.Analysis).join(models.Document).\
        filter(models.Document.user_id == user_data["id"]).\
        filter(models.Analysis.is_saved == True).\
        order_by(models.Analysis.last_updated.desc()).all()

    # Get Recent Analyses (Not Saved, last 10)
    recent_analyses = db.query(models.Analysis).join(models.Document).\
        filter(models.Document.user_id == user_data["id"]).\
        filter(models.Analysis.is_saved == False).\
        order_by(models.Analysis.created_at.desc()).limit(10).all()
        
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "user": user_data,
        "saved_analyses": saved_analyses,
        "analyses": recent_analyses # Keep key 'analyses' for recent to minimize template breakage initially
    })
