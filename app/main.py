from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api import transactions, health, internal, products, profile, alerts, trends
from app.services.alert_job import run_daily_coverage_check

_scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Corre cada hora en punto; el job internamente filtra usuarios según su hora configurada
    _scheduler.add_job(run_daily_coverage_check, CronTrigger(minute=0, timezone="UTC"))
    _scheduler.start()
    yield
    _scheduler.shutdown()


# Create FastAPI app
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
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
app.include_router(transactions.router)
app.include_router(products.router)
app.include_router(profile.router)
app.include_router(alerts.router)
app.include_router(trends.router)
app.include_router(internal.router)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "TPP Backend API",
        "version": settings.API_VERSION,
        "docs": "/docs",
        "trpc": "/api",
    }
