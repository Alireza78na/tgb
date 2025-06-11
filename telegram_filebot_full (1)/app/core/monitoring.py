import logging
from typing import Optional

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Minimal metrics collector placeholder."""

    async def record_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration: float,
    ) -> None:
        logger.debug(
            "[metrics] %s %s %s %.3fs", method, path, status_code, duration
        )

    async def record_error(
        self,
        method: str,
        path: str,
        error_type: str,
        duration: float,
    ) -> None:
        logger.error(
            "[metrics] error %s %s %s %.3fs",
            method,
            path,
            error_type,
            duration,
        )


async def setup_monitoring() -> None:
    """Placeholder for monitoring setup."""
    logger.info("Monitoring is enabled")
