from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.core.db import Base, db_manager, init_database, cleanup_database
from app.api import routes_user, routes_file, routes_admin

app = FastAPI(
    title="Telegram FileBot API",
    version="1.0.0"
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
async def on_startup() -> None:
    """Create database tables on application startup."""
    await init_database()
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await cleanup_database()

# ثبت routeها
app.include_router(routes_user.router, prefix="/user", tags=["User"])
app.include_router(routes_file.router, prefix="/file", tags=["File"])
app.include_router(routes_admin.router, prefix="/admin", tags=["Admin"])


@app.get("/")
async def read_root() -> JSONResponse:
    """Simple welcome endpoint for the API root."""
    return JSONResponse({"message": "Telegram FileBot API"})
