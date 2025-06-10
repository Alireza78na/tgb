from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.core.db import engine, Base
from app.api import routes_user, routes_file, routes_admin

app = FastAPI(
    title="Telegram FileBot API",
    version="1.0.0"
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
async def on_startup() -> None:
    """Create database tables on application startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# ثبت routeها
app.include_router(routes_user.router, prefix="/user", tags=["User"])
app.include_router(routes_file.router, prefix="/file", tags=["File"])
app.include_router(routes_admin.router, prefix="/admin", tags=["Admin"])
