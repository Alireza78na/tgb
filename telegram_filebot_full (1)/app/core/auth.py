from fastapi import Request, HTTPException, Depends
from starlette.status import HTTP_401_UNAUTHORIZED
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.user import User
from app.core.db import async_session

ADMIN_TOKEN = "SuperSecretAdminToken123"

async def verify_admin_token(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Unauthorized admin access")


async def verify_user_token(token: str, db: AsyncSession) -> str | None:
    """Verify a user access token and return the associated user_id."""
    result = await db.execute(select(User).where(User.id == token))
    user = result.scalars().first()
    if user:
        return user.id
    return None


async def get_current_user(request: Request, db: AsyncSession = Depends(async_session)) -> str:
    """Extract and validate the user from headers."""
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        # fallback to X-User-Id for backward compatibility
        token = request.headers.get("X-User-Id")
    if not token:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Missing or invalid authorization header")

    user_id = await verify_user_token(token, db)
    if not user_id:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid token")

    return user_id
