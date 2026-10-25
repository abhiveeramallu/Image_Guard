from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (routes_analyze, routes_attack_lab, routes_capabilities, routes_detect, routes_forgery_lab, routes_health, routes_invisible,
                     routes_watermark)
from app.core.config import APP_VERSION, get_settings
from app.core.errors import install_error_handlers
from app.core.ratelimit import RateLimitMiddleware

settings = get_settings()

app = FastAPI(
    title="ImageGuard API",
    version=APP_VERSION,
    description="Visible watermarking and ORB-based copy-move candidate detection.",
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/api/openapi.json",
)
install_error_handlers(app)
app.add_middleware(RateLimitMiddleware, per_minute=settings.rate_limit_per_minute)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Region-Count"],
)
app.include_router(routes_health.router, prefix="/api")
app.include_router(routes_watermark.router, prefix="/api")
app.include_router(routes_detect.router, prefix="/api")
app.include_router(routes_analyze.router, prefix="/api")
app.include_router(routes_capabilities.router, prefix="/api")
app.include_router(routes_invisible.router, prefix="/api")
app.include_router(routes_attack_lab.router, prefix="/api")
app.include_router(routes_forgery_lab.router, prefix="/api")
