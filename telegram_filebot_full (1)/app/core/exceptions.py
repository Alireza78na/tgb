from __future__ import annotations

from typing import Any, Dict, Optional, Callable
from enum import Enum
from functools import wraps
import logging
from datetime import datetime
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorCode(Enum):
    """Standard error codes used across the application."""

    # File Operation Errors (1000-1099)
    FILE_NOT_FOUND = 1001
    FILE_TOO_LARGE = 1002
    FILE_TYPE_BLOCKED = 1003
    FILE_UPLOAD_FAILED = 1004
    FILE_DOWNLOAD_FAILED = 1005
    FILE_DELETE_FAILED = 1006
    FILE_CORRUPTED = 1007
    STORAGE_FULL = 1008

    # Authentication Errors (2000-2099)
    INVALID_TOKEN = 2001
    TOKEN_EXPIRED = 2002
    INSUFFICIENT_PERMISSIONS = 2003
    USER_BLOCKED = 2004
    ADMIN_ACCESS_REQUIRED = 2005

    # Subscription Errors (3000-3099)
    SUBSCRIPTION_EXPIRED = 3001
    SUBSCRIPTION_NOT_FOUND = 3002
    SUBSCRIPTION_LIMIT_EXCEEDED = 3003
    INVALID_SUBSCRIPTION_PLAN = 3004

    # Rate Limiting Errors (4000-4099)
    RATE_LIMIT_EXCEEDED = 4001
    TOO_MANY_REQUESTS = 4002

    # Database Errors (5000-5099)
    DATABASE_CONNECTION_FAILED = 5001
    DATABASE_OPERATION_FAILED = 5002
    DATA_INTEGRITY_ERROR = 5003

    # Telegram API Errors (6000-6099)
    TELEGRAM_API_ERROR = 6001
    BOT_BLOCKED_BY_USER = 6002
    INVALID_TELEGRAM_FILE_ID = 6003
    TELEGRAM_FILE_TOO_LARGE = 6004

    # General Errors (9000-9099)
    INTERNAL_SERVER_ERROR = 9001
    VALIDATION_ERROR = 9002
    CONFIGURATION_ERROR = 9003


class BaseCustomException(Exception):
    """Base class for all custom exceptions."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        details: Optional[Dict[str, Any]] = None,
        user_message: Optional[str] = None,
    ) -> None:
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.user_message = user_message or self._get_default_user_message()
        self.timestamp = datetime.utcnow()
        super().__init__(self.message)
        self._log_error()

    def _get_default_user_message(self) -> str:
        messages = {
            ErrorCode.FILE_NOT_FOUND: "فایل مورد نظر یافت نشد",
            ErrorCode.FILE_TOO_LARGE: "اندازه فایل بیش از حد مجاز است",
            ErrorCode.FILE_TYPE_BLOCKED: "نوع فایل مجاز نیست",
            ErrorCode.FILE_UPLOAD_FAILED: "آپلود فایل با خطا مواجه شد",
            ErrorCode.FILE_DOWNLOAD_FAILED: "دانلود فایل با خطا مواجه شد",
            ErrorCode.STORAGE_FULL: "فضای ذخیره‌سازی پر است",
            ErrorCode.INVALID_TOKEN: "احراز هویت نامعتبر",
            ErrorCode.TOKEN_EXPIRED: "جلسه منقضی شده است",
            ErrorCode.USER_BLOCKED: "دسترسی شما مسدود شده است",
            ErrorCode.SUBSCRIPTION_EXPIRED: "اشتراک شما منقضی شده است",
            ErrorCode.RATE_LIMIT_EXCEEDED: "تعداد درخواست‌ها بیش از حد مجاز است",
            ErrorCode.INTERNAL_SERVER_ERROR: "خطای داخلی سرور",
        }
        return messages.get(self.error_code, "خطای نامشخص")

    def _log_error(self) -> None:
        logger.error(
            "Exception: %s - Code: %s - Message: %s - Details: %s",
            self.__class__.__name__,
            self.error_code.value,
            self.message,
            self.details,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": True,
            "error_code": self.error_code.value,
            "message": self.user_message,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


# File Operation Exceptions ----------------------------------------------------
class FileOperationError(BaseCustomException):
    """Base error for file operations."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.FILE_UPLOAD_FAILED,
        file_path: Optional[str] = None,
        file_size: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.get("details", {})
        if file_path:
            details["file_path"] = file_path
        if file_size is not None:
            details["file_size"] = file_size
        kwargs["details"] = details
        super().__init__(message, error_code, **kwargs)


class FileNotFoundError(FileOperationError):
    def __init__(self, file_path: str, **kwargs: Any) -> None:
        super().__init__(
            f"File not found: {file_path}",
            ErrorCode.FILE_NOT_FOUND,
            file_path=file_path,
            **kwargs,
        )


class FileTooLargeError(FileOperationError):
    def __init__(self, file_size: int, max_size: int, **kwargs: Any) -> None:
        super().__init__(
            f"File size {file_size} exceeds maximum {max_size}",
            ErrorCode.FILE_TOO_LARGE,
            file_size=file_size,
            user_message=f"اندازه فایل نباید بیش از {max_size // (1024*1024)} مگابایت باشد",
            **kwargs,
        )


class FileTypeBlockedError(FileOperationError):
    def __init__(self, file_extension: str, **kwargs: Any) -> None:
        super().__init__(
            f"File type {file_extension} is blocked",
            ErrorCode.FILE_TYPE_BLOCKED,
            user_message=f"فایل‌های با پسوند {file_extension} مجاز نیستند",
            **kwargs,
        )


class StorageFullError(FileOperationError):
    def __init__(self, used_space: int, max_space: int, **kwargs: Any) -> None:
        super().__init__(
            f"Storage full: {used_space}/{max_space}",
            ErrorCode.STORAGE_FULL,
            user_message="فضای ذخیره‌سازی شما پر است",
            **kwargs,
        )


# Authentication Exceptions ---------------------------------------------------
class AuthenticationError(BaseCustomException):
    pass


class InvalidTokenError(AuthenticationError):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("Invalid authentication token", ErrorCode.INVALID_TOKEN, **kwargs)


class TokenExpiredError(AuthenticationError):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__("Authentication token has expired", ErrorCode.TOKEN_EXPIRED, **kwargs)


class InsufficientPermissionsError(AuthenticationError):
    def __init__(self, required_permission: str, **kwargs: Any) -> None:
        super().__init__(
            f"Insufficient permissions: {required_permission} required",
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            user_message="شما دسترسی لازم برای این عملیات را ندارید",
            **kwargs,
        )


class UserBlockedError(AuthenticationError):
    def __init__(self, user_id: str, reason: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(
            f"User {user_id} is blocked: {reason}",
            ErrorCode.USER_BLOCKED,
            user_message="دسترسی شما به سیستم مسدود شده است",
            **kwargs,
        )


# Subscription Exceptions -----------------------------------------------------
class SubscriptionError(BaseCustomException):
    pass


class SubscriptionExpiredError(SubscriptionError):
    def __init__(self, expiry_date: datetime, **kwargs: Any) -> None:
        super().__init__(
            f"Subscription expired on {expiry_date}",
            ErrorCode.SUBSCRIPTION_EXPIRED,
            details={"expiry_date": expiry_date.isoformat()},
            **kwargs,
        )


class SubscriptionLimitExceededError(SubscriptionError):
    def __init__(self, limit_type: str, current: int, maximum: int, **kwargs: Any) -> None:
        super().__init__(
            f"{limit_type} limit exceeded: {current}/{maximum}",
            ErrorCode.SUBSCRIPTION_LIMIT_EXCEEDED,
            user_message=f"محدودیت {limit_type} تجاوز شده است",
            details={"limit_type": limit_type, "current": current, "maximum": maximum},
            **kwargs,
        )


# Rate Limiting Exceptions ----------------------------------------------------
class RateLimitError(BaseCustomException):
    def __init__(self, retry_after: int, **kwargs: Any) -> None:
        super().__init__(
            f"Rate limit exceeded, retry after {retry_after} seconds",
            ErrorCode.RATE_LIMIT_EXCEEDED,
            user_message=f"لطفاً {retry_after} ثانیه صبر کنید",
            details={"retry_after": retry_after},
            **kwargs,
        )


# Database Exceptions ---------------------------------------------------------
class DatabaseError(BaseCustomException):
    pass


class DatabaseConnectionError(DatabaseError):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            "Database connection failed",
            ErrorCode.DATABASE_CONNECTION_FAILED,
            user_message="مشکل در اتصال به پایگاه داده",
            **kwargs,
        )


class DataIntegrityError(DatabaseError):
    def __init__(self, constraint: str, **kwargs: Any) -> None:
        super().__init__(
            f"Data integrity constraint violated: {constraint}",
            ErrorCode.DATA_INTEGRITY_ERROR,
            user_message="خطا در یکپارچگی داده‌ها",
            **kwargs,
        )


# Telegram API Exceptions -----------------------------------------------------
class TelegramAPIError(BaseCustomException):
    def __init__(self, api_error_code: int, api_description: str, **kwargs: Any) -> None:
        super().__init__(
            f"Telegram API Error {api_error_code}: {api_description}",
            ErrorCode.TELEGRAM_API_ERROR,
            details={"api_error_code": api_error_code, "api_description": api_description},
            **kwargs,
        )


class BotBlockedByUserError(TelegramAPIError):
    def __init__(self, user_id: str, **kwargs: Any) -> None:
        super().__init__(
            403,
            f"Bot blocked by user {user_id}",
            user_message="ربات توسط کاربر مسدود شده است",
            **kwargs,
        )


class InvalidTelegramFileIdError(TelegramAPIError):
    def __init__(self, file_id: str, **kwargs: Any) -> None:
        super().__init__(
            400,
            f"Invalid Telegram file ID: {file_id}",
            user_message="شناسه فایل نامعتبر است",
            **kwargs,
        )


# Validation Exceptions -------------------------------------------------------
class ValidationError(BaseCustomException):
    def __init__(self, field: str, value: Any, message: str, **kwargs: Any) -> None:
        super().__init__(
            f"Validation error for {field}: {message}",
            ErrorCode.VALIDATION_ERROR,
            user_message=f"خطا در {field}: {message}",
            details={"field": field, "value": str(value)},
            **kwargs,
        )


# Configuration Exceptions ----------------------------------------------------
class ConfigurationError(BaseCustomException):
    def __init__(self, config_key: str, **kwargs: Any) -> None:
        super().__init__(
            f"Configuration error: {config_key}",
            ErrorCode.CONFIGURATION_ERROR,
            user_message="خطا در تنظیمات سیستم",
            **kwargs,
        )


# ----------------------- Exception Handler Middleware -----------------------
async def custom_exception_handler(request: Request, exc: BaseCustomException) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=exc.to_dict())


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"])
        errors.append({"field": field, "message": error["msg"], "type": error["type"]})
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": True,
            "error_code": ErrorCode.VALIDATION_ERROR.value,
            "message": "خطا در اعتبارسنجی داده‌ها",
            "details": {"validation_errors": errors},
        },
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    user_messages = {404: "منبع مورد نظر یافت نشد", 405: "متد HTTP مجاز نیست", 500: "خطای داخلی سرور"}
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "error_code": exc.status_code,
            "message": user_messages.get(exc.status_code, "خطای HTTP"),
            "details": {"http_detail": exc.detail},
        },
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": True,
            "error_code": ErrorCode.INTERNAL_SERVER_ERROR.value,
            "message": "خطای داخلی سرور",
            "details": {"error_type": type(exc).__name__} if logger.level <= logging.DEBUG else {},
        },
    )


def register_exception_handlers(app: Any) -> None:
    app.add_exception_handler(BaseCustomException, custom_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)


# --------------------------- Utility Decorators -----------------------------
def handle_file_operation(func: Callable) -> Callable:
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except OSError as e:
            if e.errno == 28:
                raise StorageFullError(0, 0, details={"os_error": str(e)})
            if e.errno == 2:
                raise FileNotFoundError("unknown", details={"os_error": str(e)})
            raise FileOperationError(
                f"OS error during file operation: {e}", details={"os_error": str(e), "errno": e.errno}
            )
        except PermissionError as e:
            raise FileOperationError(
                f"Permission denied: {e}", ErrorCode.FILE_UPLOAD_FAILED, details={"permission_error": str(e)}
            )
    return wrapper


def handle_database_operation(func: Callable) -> Callable:
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if "connection" in str(e).lower():
                raise DatabaseConnectionError(details={"db_error": str(e)})
            raise DatabaseError(
                f"Database operation failed: {e}", ErrorCode.DATABASE_OPERATION_FAILED, details={"db_error": str(e)}
            )
    return wrapper


class ExceptionContext:
    def __init__(self, operation_name: str, user_id: Optional[str] = None) -> None:
        self.operation_name = operation_name
        self.user_id = user_id

    async def __aenter__(self) -> "ExceptionContext":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type and not issubclass(exc_type, BaseCustomException):
            logger.error(
                "Unhandled exception in %s: %s", self.operation_name, exc_val, extra={"user_id": self.user_id}
            )
            if issubclass(exc_type, OSError):
                raise FileOperationError(
                    f"File operation failed in {self.operation_name}", details={"original_error": str(exc_val)}
                )
        return False
