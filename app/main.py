from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api import auth, transactions, health, products
from app.routers import api as api_router

# Create FastAPI app
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    debug=settings.DEBUG,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(products.router)
app.include_router(api_router.router)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "TPP Backend API",
        "version": settings.API_VERSION,
        "docs": "/docs",
        "trpc": "/api",
    }
