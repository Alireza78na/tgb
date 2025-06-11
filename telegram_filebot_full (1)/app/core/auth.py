import os
import secrets
import hashlib
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import jwt
from passlib.context import CryptContext
from fastapi import Request, HTTPException, Depends
from starlette.status import HTTP_401_UNAUTHORIZED
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.user import User
from app.models.user_token import UserToken
from app.core.db import async_session

logger = logging.getLogger(__name__)

# Security settings
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
ADMIN_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenManager:
    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        to_encode = data.copy()
        expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        to_encode.update({"exp": expire, "iat": datetime.utcnow()})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt

    @staticmethod
    def verify_token(token: str) -> Optional[dict]:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.PyJWTError:
            return None


class AdminTokenManager:
    def __init__(self) -> None:
        self.active_tokens: dict[str, dict] = {}

    def create_admin_token(self, admin_id: str) -> str:
        token_data = {
            "sub": admin_id,
            "type": "admin",
            "permissions": ["read", "write", "delete"],
        }
        expires = timedelta(minutes=ADMIN_TOKEN_EXPIRE_MINUTES)
        token = TokenManager.create_access_token(token_data, expires)
        self.active_tokens[token] = {
            "admin_id": admin_id,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + expires,
        }
        return token

    def verify_admin_token(self, token: str) -> Optional[str]:
        payload = TokenManager.verify_token(token)
        if not payload or payload.get("type") != "admin":
            return None
        if token in self.active_tokens:
            info = self.active_tokens[token]
            if datetime.utcnow() > info["expires_at"]:
                del self.active_tokens[token]
                return None
            return info["admin_id"]
        return None

    def revoke_token(self, token: str) -> None:
        if token in self.active_tokens:
            del self.active_tokens[token]


admin_token_manager = AdminTokenManager()


class SecureAuth:
    @staticmethod
    async def create_user_token(
        user_id: str,
        device_info: str,
        db: AsyncSession,
        expires_hours: int = 24,
    ) -> str:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        db_token = UserToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=datetime.utcnow() + timedelta(hours=expires_hours),
            device_info=device_info,
        )
        db.add(db_token)
        await SecureAuth.cleanup_expired_tokens(db, user_id)
        await db.commit()
        logger.info(f"Created token for user {user_id}")
        return raw_token

    @staticmethod
    async def verify_user_token(token: str, db: AsyncSession) -> Optional[str]:
        if not token or len(token) < 10:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        result = await db.execute(
            select(UserToken).join(User, UserToken.user_id == User.id).where(
                UserToken.token_hash == token_hash,
                UserToken.is_active == True,
                UserToken.expires_at > datetime.utcnow(),
                User.is_blocked == False,
            )
        )
        user_token = result.scalars().first()
        if user_token:
            user_token.last_used = datetime.utcnow()
            await db.commit()
            return user_token.user_id
        return None

    @staticmethod
    async def cleanup_expired_tokens(db: AsyncSession, user_id: Optional[str] = None) -> None:
        query = select(UserToken).where(UserToken.expires_at < datetime.utcnow())
        if user_id:
            query = query.where(UserToken.user_id == user_id)
        result = await db.execute(query)
        for token in result.scalars():
            await db.delete(token)


class RateLimiter:
    def __init__(self) -> None:
        self.failed_attempts: dict[str, tuple[int, float]] = {}
        self.block_time = 300
        self.max_attempts = 5

    def is_blocked(self, ip: str) -> bool:
        if ip in self.failed_attempts:
            attempts, last_attempt = self.failed_attempts[ip]
            if attempts >= self.max_attempts:
                if time.time() - last_attempt < self.block_time:
                    return True
                del self.failed_attempts[ip]
        return False

    def record_failed_attempt(self, ip: str) -> None:
        if ip in self.failed_attempts:
            attempts, _ = self.failed_attempts[ip]
            self.failed_attempts[ip] = (attempts + 1, time.time())
        else:
            self.failed_attempts[ip] = (1, time.time())

    def clear_attempts(self, ip: str) -> None:
        if ip in self.failed_attempts:
            del self.failed_attempts[ip]


rate_limiter = RateLimiter()


async def verify_admin_token(request: Request) -> str:
    client_ip = request.client.host
    if rate_limiter.is_blocked(client_ip):
        logger.warning(f"Blocked admin login attempt from {client_ip}")
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        rate_limiter.record_failed_attempt(client_ip)
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth_header[7:]
    admin_id = admin_token_manager.verify_admin_token(token)
    if not admin_id:
        rate_limiter.record_failed_attempt(client_ip)
        logger.warning(f"Failed admin authentication from {client_ip}")
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid or expired admin token")
    rate_limiter.clear_attempts(client_ip)
    logger.info(f"Successful admin authentication: {admin_id}")
    return admin_id


async def get_current_user(request: Request, db: AsyncSession = Depends(async_session)) -> str:
    client_ip = request.client.host
    if rate_limiter.is_blocked(client_ip):
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        rate_limiter.record_failed_attempt(client_ip)
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:]
    user_id = await SecureAuth.verify_user_token(token, db)
    if not user_id:
        rate_limiter.record_failed_attempt(client_ip)
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    rate_limiter.clear_attempts(client_ip)
    return user_id

