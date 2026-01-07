"""
Session inactivity timeout middleware
"""
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from datetime import datetime, timedelta

# Inactivity timeout: 2 hours
INACTIVITY_TIMEOUT_HOURS = 2


class SessionInactivityMiddleware(BaseHTTPMiddleware):
    """
    Middleware to check session inactivity and auto-logout users.
    Tracks last_activity timestamp in session.
    """
    
    async def dispatch(self, request: Request, call_next):
        # Skip auth check for public endpoints
        public_paths = [
            "/api/health",
            "/health",
            "/api/auth/login",
            "/api/auth/forgot-password",
            "/api/auth/reset-password",
            "/api/stripe/webhook",
            "/api/stripe/prices",
            "/docs",
            "/openapi.json"
        ]
        
        if request.url.path in public_paths or request.url.path.startswith("/static"):
            return await call_next(request)
        
        # Check if user is authenticated
        if "user" in request.session:
            # Check last activity
            if "last_activity" in request.session:
                try:
                    last_activity = datetime.fromisoformat(request.session["last_activity"])
                    time_since_activity = datetime.utcnow() - last_activity
                    
                    # If inactive for too long, clear session
                    if time_since_activity > timedelta(hours=INACTIVITY_TIMEOUT_HOURS):
                        request.session.clear()
                        raise HTTPException(
                            status_code=401,
                            detail="Session expired due to inactivity. Please login again."
                        )
                except (ValueError, TypeError):
                    # Invalid timestamp, clear and require re-login
                    request.session.clear()
                    raise HTTPException(status_code=401, detail="Invalid session")
            
            # 🔒 BUGFIX: Update last activity BEFORE call_next() to prevent race condition
            # If updated after, concurrent requests could both see old timestamp
            request.session["last_activity"] = datetime.utcnow().isoformat()
        
        response = await call_next(request)
        return response
