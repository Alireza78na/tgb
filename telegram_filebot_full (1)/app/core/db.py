import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Any, Dict, List, Optional, Type, TypeVar

from sqlalchemy import event, text, select, update, delete, func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import QueuePool, StaticPool

from app.core.config import config

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Advanced database connection manager."""

    def __init__(self) -> None:
        self.engine: Optional[Any] = None
        self.session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        engine_kwargs: Dict[str, Any] = {
            "echo": config.DATABASE_ECHO,
            "future": True,
            "pool_pre_ping": True,
        }

        if "sqlite" in config.DATABASE_URL:
            engine_kwargs.update(
                {
                    "poolclass": StaticPool,
                    "connect_args": {
                        "check_same_thread": False,
                        "timeout": 30,
                        "isolation_level": None,
                    },
                }
            )
        else:
            engine_kwargs.update(
                {
                    "poolclass": QueuePool,
                    "pool_size": 20,
                    "max_overflow": 50,
                    "pool_timeout": 30,
                    "pool_recycle": 3600,
                    "pool_reset_on_return": "commit",
                }
            )

        self.engine = create_async_engine(config.DATABASE_URL, **engine_kwargs)
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

        await self._setup_event_listeners()
        await self._health_check()

        self._initialized = True
        logger.info("Database initialized")

    async def _setup_event_listeners(self) -> None:
        if not self.engine:
            return

        @event.listens_for(self.engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            if "sqlite" in config.DATABASE_URL:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA cache_size=10000")
                cursor.execute("PRAGMA temp_store=MEMORY")
                cursor.execute("PRAGMA mmap_size=268435456")
                cursor.close()

        @event.listens_for(self.engine.sync_engine, "checkout")
        def checkout_listener(dbapi_connection, connection_record, connection_proxy):
            connection_record.info["checkout_time"] = time.time()

        @event.listens_for(self.engine.sync_engine, "checkin")
        def checkin_listener(dbapi_connection, connection_record):
            checkout_time = connection_record.info.get("checkout_time")
            if checkout_time:
                duration = time.time() - checkout_time
                if duration > 10:
                    logger.warning(f"Long running connection: {duration:.2f}s")

    async def _health_check(self) -> None:
        if not self.session_factory:
            return
        try:
            async with self.session_factory() as session:
                result = await session.execute(text("SELECT 1"))
                result.fetchone()
                logger.info("Database health check passed")
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            raise

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        if not self._initialized:
            await self.initialize()
        assert self.session_factory
        session = self.session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def close(self) -> None:
        if self.engine:
            await self.engine.dispose()
            logger.info("Database connections closed")


db_manager = DatabaseManager()
Base = declarative_base()

# Backwards compatibility
async_session = db_manager.get_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with db_manager.get_session() as session:
        yield session


# ----------------------- Utility Services ---------------------------
T = TypeVar("T", bound=Base)


class DatabaseService:
    """Common database utilities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, model: Type[T], id: Any) -> Optional[T]:
        result = await self.session.execute(select(model).where(model.id == id))
        return result.scalars().first()

    async def get_all(
        self,
        model: Type[T],
        limit: int = 100,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None,
        order_by: Optional[str] = None,
    ) -> List[T]:
        query = select(model)
        if filters:
            for field, value in filters.items():
                if hasattr(model, field):
                    column = getattr(model, field)
                    if isinstance(value, list):
                        query = query.where(column.in_(value))
                    else:
                        query = query.where(column == value)
        if order_by and hasattr(model, order_by):
            query = query.order_by(getattr(model, order_by))
        query = query.offset(offset).limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def count(
        self, model: Type[T], filters: Optional[Dict[str, Any]] = None
    ) -> int:
        query = select(func.count(model.id))
        if filters:
            for field, value in filters.items():
                if hasattr(model, field):
                    column = getattr(model, field)
                    query = query.where(column == value)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def create(self, model: Type[T], **kwargs: Any) -> T:
        instance = model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update_by_id(self, model: Type[T], id: Any, **kwargs: Any) -> bool:
        result = await self.session.execute(
            update(model).where(model.id == id).values(**kwargs)
        )
        return result.rowcount > 0

    async def delete_by_id(self, model: Type[T], id: Any) -> bool:
        result = await self.session.execute(delete(model).where(model.id == id))
        return result.rowcount > 0


async def init_database() -> None:
    await db_manager.initialize()


async def cleanup_database() -> None:
    await db_manager.close()

