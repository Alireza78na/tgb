from fastapi import Request, HTTPException
from starlette.status import HTTP_401_UNAUTHORIZED

ADMIN_TOKEN = "SuperSecretAdminToken123"

async def verify_admin_token(request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Unauthorized admin access")
