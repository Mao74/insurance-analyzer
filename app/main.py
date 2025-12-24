from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
from .config import settings
from .database import engine, Base, init_db
from .routes import auth_routes, upload_routes, analysis_routes, claims_routes, admin_routes
import uvicorn

app = FastAPI(title="PoliSight API", version="2.0.0")

# CORS Configuration - MUST be added first (will be outermost)
origins = [
    "http://localhost:3000",
    "http://localhost:5173",  # Vite dev server
    "http://localhost:5174",  # Vite alternate port
    "http://localhost:8000",
    "http://localhost:8001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8001",
    "https://app.insurance-lab.ai",
    "https://*.insurance-lab.ai",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Custom Auth Middleware Class (to control execution order)
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Public routes that don't require authentication
        public_paths = [
            "/api/health",
            "/health",  # Docker health check
            "/api/auth/login",
            "/api/auth/forgot-password",
            "/api/auth/reset-password",
            "/static",
            "/docs",
            "/openapi.json",
            "/redoc"
        ]
        
        path = request.url.path
        method = request.method
        
        # Allow OPTIONS requests (CORS preflight)
        if method == "OPTIONS":
            response = await call_next(request)
            return response
        
        # Allow public paths
        if any(path.startswith(p) for p in public_paths):
            response = await call_next(request)
            return response
        
        # Check session for protected /api/ routes
        if path.startswith("/api/"):
            user = request.session.get("user")
            if not user:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Not authenticated"}
                )
        
        response = await call_next(request)
        return response


# MIDDLEWARE ORDER IS CRITICAL!
# They execute in REVERSE order of addition:
# 1. SessionMiddleware (added LAST, runs FIRST - sets up session)
# 2. AuthMiddleware (added second-to-last, runs after session is available)
# 3. CORSMiddleware (added first, runs last - handles CORS headers)

# Add AuthMiddleware
app.add_middleware(AuthMiddleware)

# Session Middleware - MUST be added LAST to run FIRST
app.add_middleware(
    SessionMiddleware, 
    secret_key=settings.SECRET_KEY, 
    max_age=settings.SESSION_TIMEOUT_HOURS * 3600,
    https_only=False,  # Set True in production with SSL
    same_site="lax"    # Revert to lax now that we use proxy (Same-Origin)
)

# Static files (for uploaded files access if needed)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Health check endpoints
@app.get("/api/health")
@app.get("/health")  # Alias for Docker health check
async def health_check():
    return {"status": "healthy", "version": "2.0.0", "message": "PoliSight API is running"}

# Include routers with /api prefix
app.include_router(auth_routes.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(upload_routes.router, prefix="/api/documents", tags=["Documents"])
app.include_router(analysis_routes.router, prefix="/api/analysis", tags=["Analysis"])
app.include_router(claims_routes.router, prefix="/api/claims", tags=["Claims"])
app.include_router(admin_routes.router, prefix="/api/admin", tags=["Admin"])

@app.on_event("startup")
def on_startup():
    init_db()

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
