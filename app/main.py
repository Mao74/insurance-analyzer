
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import RedirectResponse
from .config import settings
from .database import engine, Base, init_db
from .routes import auth_routes, upload_routes, analysis_routes
import uvicorn

# Initialize tables
# Base.metadata.create_all(bind=engine) # moved to init_db command but good to have safety?
# Let's rely on init_db() called manually or on startup.
# We will call it on startup event for MVP simplicity.

app = FastAPI(title="PoliSight")


# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Auth Middleware to protect routes
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Public routes
    public_routes = ["/login", "/static", "/docs", "/openapi.json"]
    
    path = request.url.path
    if path == "/" or any(path.startswith(p) for p in public_routes):
        response = await call_next(request)
        return response
        
    # Check session
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
        
    response = await call_next(request)
    return response

# Middleware (Session must be added LAST to be OUTERMOST/FIRST executed)
app.add_middleware(
    SessionMiddleware, 
    secret_key=settings.SECRET_KEY, 
    max_age=settings.SESSION_TIMEOUT_HOURS * 3600,
    https_only=False, # Set True in production with SSL
    same_site="strict"
)

# Include routers
app.include_router(auth_routes.router)
app.include_router(upload_routes.router)
app.include_router(analysis_routes.router)

@app.on_event("startup")
def on_startup():
    init_db()

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
