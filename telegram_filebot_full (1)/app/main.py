import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, Request, Response, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import config
from app.core.db import Base, db_manager, init_database, cleanup_database
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging, get_logger
from app.core.monitoring import setup_monitoring, MetricsCollector
from app.core.security import SecurityMiddleware, setup_security_headers
from app.core.rate_limiting import RateLimiter

from app.api import routes_user, routes_file, routes_admin
from app.services.task_queue import start_task_queue, stop_task_queue
from app.services.cleanup import cleanup_service, scheduled_cleanup
from app.services.subscription_reminder import scheduled_reminder_task

logger = get_logger(__name__)


class PerformanceMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, metrics_collector: Optional[MetricsCollector] = None):
        super().__init__(app)
        self.metrics_collector = metrics_collector or MetricsCollector()

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            await self.metrics_collector.record_request(
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration=process_time,
            )
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = str(process_time)
            return response
        except Exception as exc:
            process_time = time.time() - start_time
            await self.metrics_collector.record_error(
                method=request.method,
                path=request.url.path,
                error_type=type(exc).__name__,
                duration=process_time,
            )
            logger.error("Request %s failed: %s", request_id, exc, exc_info=True)
            raise


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        logger.info(
            "Request started",
            extra={
                "request_id": getattr(request.state, "request_id", "unknown"),
                "method": request.method,
                "url": str(request.url),
            },
        )
        response = await call_next(request)
        logger.info(
            "Request completed",
            extra={
                "request_id": getattr(request.state, "request_id", "unknown"),
                "status_code": response.status_code,
                "response_time": response.headers.get("X-Process-Time", "unknown"),
            },
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Telegram FileBot API...")
    try:
        await init_database()
        async with db_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await start_task_queue()
        asyncio.create_task(scheduled_cleanup())
        asyncio.create_task(scheduled_reminder_task())
        await setup_monitoring()
        yield
    finally:
        await stop_task_queue()
        await cleanup_database()
        logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        title="Telegram FileBot API",
        description="Advanced API for Telegram FileBot",
        version="2.0.0",
        lifespan=lifespan,
    )

    if config.ENVIRONMENT == "production":
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.SECRET_KEY,
        max_age=86400,
        same_site="lax",
        https_only=config.ENVIRONMENT == "production",
    )

    app.add_middleware(SecurityMiddleware)
    app.add_middleware(PerformanceMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    register_exception_handlers(app)

    setup_static_files(app)
    setup_routes(app)
    setup_rate_limiting(app)
    setup_security_headers(app)
    setup_health_checks(app)

    return app


def setup_static_files(app: FastAPI) -> None:
    static_dir = Path("app/static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    templates_dir = Path("app/templates")
    if templates_dir.exists():
        app.state.templates = Jinja2Templates(directory=str(templates_dir))


def setup_routes(app: FastAPI) -> None:
    app.include_router(routes_user.router, prefix="/user", tags=["User"])
    app.include_router(routes_file.router, prefix="/file", tags=["File"])
    app.include_router(routes_admin.router, prefix="/admin", tags=["Admin"])


def setup_rate_limiting(app: FastAPI) -> None:
    rate_limiter = RateLimiter(config.RATE_LIMIT_PER_MINUTE, burst_multiplier=2)

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        if not await rate_limiter.is_allowed(client_ip):
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"error": "Rate limit exceeded"},
            )
        return await call_next(request)


def setup_health_checks(app: FastAPI) -> None:
    @app.get("/health", tags=["Health"])
    async def health_check():
        try:
            async with db_manager.get_session() as session:
                await session.execute("SELECT 1")
            return {"status": "healthy"}
        except Exception as exc:  # pragma: no cover - simple check
            logger.error("Health check failed: %s", exc)
            return JSONResponse(status_code=503, content={"status": "unhealthy"})

    @app.get("/ready", tags=["Health"])
    async def readiness_check():
        try:
            async with db_manager.get_session() as session:
                await session.execute("SELECT 1")
            return {"status": "ready"}
        except Exception:
            return JSONResponse(status_code=503, content={"status": "not ready"})


def create_root_endpoints(app: FastAPI) -> None:
    pass


app = create_app()


@app.get("/", response_model=Dict[str, Any], tags=["Root"])
async def read_root() -> Dict[str, Any]:
    return {
        "message": "Telegram FileBot API",
        "version": "2.0.0",
        "environment": config.ENVIRONMENT,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/info", tags=["Info"])
async def system_info():
    if not config.DEBUG:
        raise HTTPException(status_code=404, detail="Not found")
    import platform
    import psutil

    return {
        "system": {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cpu_count": psutil.cpu_count(),
            "memory_total": psutil.virtual_memory().total,
            "disk_usage": psutil.disk_usage("/").percent,
        },
        "application": {
            "debug": config.DEBUG,
            "environment": config.ENVIRONMENT,
            "database_url": (config.DATABASE_URL[:20] + "...") if config.DATABASE_URL else None,
        },
    }


@app.middleware("http")
async def add_startup_time(request: Request, call_next):
    if not hasattr(app.state, "start_time"):
        app.state.start_time = time.time()
    response = await call_next(request)
    return response


def run_dev_server():
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


def run_production_server():
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        workers=4,
        log_level="info",
    )


if __name__ == "__main__":  # pragma: no cover - entry point
    if config.ENVIRONMENT == "development":
        run_dev_server()
    else:
        run_production_server()
