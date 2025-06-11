from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Deque, Dict, Optional, Tuple

import aioredis
import logging
import time
from collections import defaultdict, deque

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import RateLimitError, UserBlockedError
from app.models.user import User

logger = logging.getLogger(__name__)


class BlockType(Enum):
    """Possible block types."""

    PERMANENT = "permanent"
    TEMPORARY = "temporary"
    IP_BASED = "ip_based"
    SPAM_DETECTED = "spam_detected"
    ABUSE_REPORTED = "abuse_reported"
    MANUAL_ADMIN = "manual_admin"


class UserStatus(Enum):
    """User account status."""

    ACTIVE = "active"
    BLOCKED = "blocked"
    SUSPENDED = "suspended"
    PENDING_VERIFICATION = "pending_verification"
    DELETED = "deleted"


class UserBlock:
    """Information about a user block."""

    def __init__(
        self,
        user_id: str,
        block_type: BlockType,
        reason: str,
        blocked_at: datetime,
        blocked_until: Optional[datetime] = None,
        blocked_by: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.user_id = user_id
        self.block_type = block_type
        self.reason = reason
        self.blocked_at = blocked_at
        self.blocked_until = blocked_until
        self.blocked_by = blocked_by
        self.details = details or {}


class SecurityEvent:
    """Simple security event container."""

    def __init__(
        self,
        user_id: str,
        event_type: str,
        severity: str,
        description: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.user_id = user_id
        self.event_type = event_type
        self.severity = severity
        self.description = description
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.timestamp = datetime.utcnow()
        self.details = details or {}


class AdvancedUserGuard:
    """Advanced user access guard with caching and rate limiting."""

    def __init__(self, redis_client: Optional[aioredis.Redis] = None) -> None:
        self.redis = redis_client
        self.rate_limits: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=100))
        self.security_events: Deque[SecurityEvent] = deque(maxlen=1000)
        self.suspicious_ips: set[str] = set()
        self.cache_ttl = 300
        self.rate_limit_rules = {
            "api_calls": {"limit": 60, "window": 60},
            "file_uploads": {"limit": 10, "window": 60},
            "login_attempts": {"limit": 5, "window": 300},
        }

    @asynccontextmanager
    async def _get_session(self, provided: Optional[AsyncSession] = None):
        if provided is not None:
            yield provided
        else:
            async with get_db() as session:
                yield session

    async def _get_cached_user_status(
        self, user_id: str
    ) -> Optional[Tuple[UserStatus, Optional[UserBlock]]]:
        if not self.redis:
            return None
        try:
            data = await self.redis.get(f"user_status:{user_id}")
            if data:
                import json

                payload = json.loads(data)
                status = UserStatus(payload["status"])
                block_info = None
                if payload.get("block_info"):
                    bi = payload["block_info"]
                    block_info = UserBlock(
                        user_id=user_id,
                        block_type=BlockType(bi["block_type"]),
                        reason=bi["reason"],
                        blocked_at=datetime.fromisoformat(bi["blocked_at"]),
                        blocked_until=datetime.fromisoformat(bi["blocked_until"])
                        if bi.get("blocked_until")
                        else None,
                        blocked_by=bi.get("blocked_by"),
                        details=bi.get("details"),
                    )
                return status, block_info
        except Exception as exc:  # pragma: no cover - cache failures shouldn't crash
            logger.error("Error retrieving cached status: %s", exc)
        return None

    async def _cache_user_status(
        self, user_id: str, status: UserStatus, block_info: Optional[UserBlock]
    ) -> None:
        if not self.redis:
            return
        try:
            import json

            payload = {
                "status": status.value,
                "block_info": None,
            }
            if block_info:
                payload["block_info"] = {
                    "block_type": block_info.block_type.value,
                    "reason": block_info.reason,
                    "blocked_at": block_info.blocked_at.isoformat(),
                    "blocked_until": block_info.blocked_until.isoformat()
                    if block_info.blocked_until
                    else None,
                    "blocked_by": block_info.blocked_by,
                    "details": block_info.details,
                }
            await self.redis.setex(
                f"user_status:{user_id}", self.cache_ttl, json.dumps(payload)
            )
        except Exception as exc:  # pragma: no cover - cache failures shouldn't crash
            logger.error("Error caching user status: %s", exc)

    async def _invalidate_user_cache(self, user_id: str) -> None:
        if self.redis:
            try:
                await self.redis.delete(f"user_status:{user_id}")
            except Exception as exc:  # pragma: no cover - cache failures shouldn't crash
                logger.error("Error deleting user cache: %s", exc)

    async def _get_block_info(
        self, session: AsyncSession, user_id: str
    ) -> Optional[UserBlock]:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if user and user.is_blocked:
            return UserBlock(
                user_id=user_id,
                block_type=BlockType(user.block_type or BlockType.MANUAL_ADMIN.value),
                reason=user.block_reason or "blocked",
                blocked_at=user.blocked_at or datetime.utcnow(),
                blocked_until=user.blocked_until,
                blocked_by=user.blocked_by,
                details={},
            )
        return None

    async def get_user_status(
        self,
        user_id: str,
        db: Optional[AsyncSession] = None,
        use_cache: bool = True,
    ) -> Tuple[UserStatus, Optional[UserBlock]]:
        if use_cache:
            cached = await self._get_cached_user_status(user_id)
            if cached:
                return cached
        async with self._get_session(db) as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalars().first()
            if not user:
                return UserStatus.DELETED, None
            if user.is_blocked:
                status = UserStatus.BLOCKED
                block_info = await self._get_block_info(session, user_id)
            else:
                status = UserStatus.ACTIVE
                block_info = None
            if use_cache:
                await self._cache_user_status(user_id, status, block_info)
            return status, block_info

    async def ensure_not_blocked(
        self,
        user_id: str,
        request: Optional[Request] = None,
        db: Optional[AsyncSession] = None,
    ) -> None:
        status, block_info = await self.get_user_status(user_id, db)
        if status == UserStatus.BLOCKED:
            await self._handle_blocked_user(user_id, block_info, request)
        if request:
            await self._log_user_activity(user_id, request)

    async def _handle_blocked_user(
        self,
        user_id: str,
        block_info: Optional[UserBlock],
        request: Optional[Request],
    ) -> None:
        if not block_info:
            raise UserBlockedError(user_id, "blocked")
        if (
            block_info.block_type == BlockType.TEMPORARY
            and block_info.blocked_until
            and datetime.utcnow() > block_info.blocked_until
        ):
            await self._unblock_user(user_id, "temporary block expired")
            return
        if request:
            await self._log_security_event(
                user_id,
                "blocked_user_access_attempt",
                "medium",
                "Blocked user attempted access",
                ip_address=request.client.host if request else None,
                details={"block_type": block_info.block_type.value},
            )
        message = {
            BlockType.PERMANENT: "حساب کاربری شما به صورت دائمی مسدود شده است",
            BlockType.TEMPORARY: (
                f"حساب شما تا {block_info.blocked_until} مسدود است"
                if block_info.blocked_until
                else "دسترسی شما مسدود شده است"
            ),
            BlockType.SPAM_DETECTED: "حساب شما به دلیل فعالیت اسپم مسدود شده است",
            BlockType.ABUSE_REPORTED: "حساب شما به دلیل گزارش سوءاستفاده مسدود شده است",
            BlockType.MANUAL_ADMIN: "حساب شما توسط مدیر مسدود شده است",
        }.get(block_info.block_type, "دسترسی شما مسدود شده است")
        raise UserBlockedError(user_id, block_info.reason, user_message=message)

    async def check_rate_limit(
        self, user_id: str, action: str, request: Optional[Request] = None
    ) -> bool:
        if action not in self.rate_limit_rules:
            return True
        rule = self.rate_limit_rules[action]
        now = time.time()
        user_key = f"{user_id}:{action}"
        requests = self.rate_limits[user_key]
        while requests and now - requests[0] > rule["window"]:
            requests.popleft()
        if len(requests) >= rule["limit"]:
            await self._log_security_event(
                user_id,
                "rate_limit_exceeded",
                "medium",
                f"Rate limit exceeded for {action}",
                ip_address=request.client.host if request else None,
                details={"action": action, "limit": rule["limit"], "window": rule["window"]},
            )
            retry_after = rule["window"] - (now - requests[0])
            raise RateLimitError(int(retry_after))
        requests.append(now)
        return True

    async def block_user(
        self,
        user_id: str,
        block_type: BlockType,
        reason: str,
        duration_hours: Optional[int] = None,
        blocked_by: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        db: Optional[AsyncSession] = None,
    ) -> None:
        async with self._get_session(db) as session:
            blocked_until = None
            if duration_hours and block_type == BlockType.TEMPORARY:
                blocked_until = datetime.utcnow() + timedelta(hours=duration_hours)
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    is_blocked=True,
                    blocked_at=datetime.utcnow(),
                    blocked_until=blocked_until,
                    blocked_by=blocked_by,
                    block_reason=reason,
                    block_type=block_type.value,
                )
            )
            await session.commit()
        await self._log_security_event(
            user_id,
            "user_blocked",
            "high",
            f"User blocked: {reason}",
            details={
                "block_type": block_type.value,
                "duration_hours": duration_hours,
                "blocked_by": blocked_by,
                **(details or {}),
            },
        )
        await self._invalidate_user_cache(user_id)
        logger.info("User %s blocked: %s", user_id, reason)

    async def unblock_user(
        self,
        user_id: str,
        reason: str,
        unblocked_by: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> None:
        await self._unblock_user(user_id, reason, unblocked_by, db)

    async def _unblock_user(
        self,
        user_id: str,
        reason: str,
        unblocked_by: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> None:
        async with self._get_session(db) as session:
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    is_blocked=False,
                    blocked_at=None,
                    blocked_until=None,
                    blocked_by=None,
                    block_reason=None,
                    block_type=None,
                    unblocked_at=datetime.utcnow(),
                    unblocked_by=unblocked_by,
                )
            )
            await session.commit()
        await self._log_security_event(
            user_id,
            "user_unblocked",
            "medium",
            f"User unblocked: {reason}",
            details={"unblocked_by": unblocked_by},
        )
        await self._invalidate_user_cache(user_id)
        logger.info("User %s unblocked: %s", user_id, reason)

    async def detect_suspicious_activity(
        self, user_id: str, request: Request, activity_type: str
    ) -> None:
        client_ip = request.client.host
        if client_ip in self.suspicious_ips:
            await self._log_security_event(
                user_id,
                "suspicious_ip_activity",
                "high",
                "Activity from suspicious IP",
                ip_address=client_ip,
                details={"activity_type": activity_type},
            )
        user_agent = request.headers.get("User-Agent", "")
        if self._is_suspicious_user_agent(user_agent):
            await self._log_security_event(
                user_id,
                "suspicious_user_agent",
                "medium",
                "Suspicious User-Agent",
                ip_address=client_ip,
                details={"user_agent": user_agent},
            )

    def _is_suspicious_user_agent(self, user_agent: str) -> bool:
        patterns = [
            "bot",
            "crawler",
            "spider",
            "scraper",
            "wget",
            "curl",
            "python-requests",
        ]
        ua = user_agent.lower()
        return any(p in ua for p in patterns)

    async def _log_user_activity(self, user_id: str, request: Request) -> None:
        await self._log_security_event(
            user_id,
            "user_activity",
            "low",
            "User activity",
            ip_address=request.client.host,
            user_agent=request.headers.get("User-Agent"),
            details={"endpoint": str(request.url)},
        )

    async def _log_security_event(
        self,
        user_id: str,
        event_type: str,
        severity: str,
        description: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        event = SecurityEvent(
            user_id,
            event_type,
            severity,
            description,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details,
        )
        self.security_events.append(event)
        if severity in {"high", "critical"}:
            logger.warning(
                "Security event: %s - %s - User: %s", event_type, description, user_id
            )


user_guard = AdvancedUserGuard()


async def ensure_not_blocked(user_id: str) -> None:
    await user_guard.ensure_not_blocked(user_id)
