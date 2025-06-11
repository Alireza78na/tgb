import asyncio
import logging
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
import uuid
import pickle
import aioredis
import signal
import psutil

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TaskPriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class TaskType(Enum):
    FILE_UPLOAD = "file_upload"
    FILE_DOWNLOAD = "file_download"
    FILE_PROCESS = "file_process"
    FILE_CLEANUP = "file_cleanup"
    NOTIFICATION = "notification"
    SUBSCRIPTION_CHECK = "subscription_check"
    VIRUS_SCAN = "virus_scan"
    THUMBNAIL_GENERATE = "thumbnail_generate"
    ARCHIVE_CREATE = "archive_create"
    BACKUP = "backup"


@dataclass
class TaskResult:
    success: bool
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0
    memory_used: Optional[int] = None
    retries_used: int = 0


@dataclass
class TaskConfig:
    max_retries: int = 3
    retry_delay: float = 1.0
    timeout: Optional[float] = 300
    priority: TaskPriority = TaskPriority.NORMAL
    task_type: TaskType = TaskType.FILE_PROCESS
    max_memory_mb: Optional[int] = None
    requires_user_subscription: bool = False


@dataclass
class Task:
    id: str
    func: Callable
    args: tuple
    kwargs: dict
    config: TaskConfig
    created_at: datetime
    status: TaskStatus = TaskStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retries: int = 0
    error_history: List[str] = None
    result: Optional[TaskResult] = None
    worker_id: Optional[str] = None
    user_id: Optional[str] = None

    def __post_init__(self):
        if self.error_history is None:
            self.error_history = []


class TaskStorage(ABC):
    @abstractmethod
    async def save_task(self, task: Task) -> bool:
        pass

    @abstractmethod
    async def get_task(self, task_id: str) -> Optional[Task]:
        pass

    @abstractmethod
    async def update_task_status(self, task_id: str, status: TaskStatus) -> bool:
        pass

    @abstractmethod
    async def get_pending_tasks(self, limit: int = 100) -> List[Task]:
        pass

    @abstractmethod
    async def cleanup_old_tasks(self, older_than_days: int = 7) -> int:
        pass


class RedisTaskStorage(TaskStorage):
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
        self.task_prefix = "task:"
        self.queue_prefix = "queue:"

    async def connect(self):
        if not self.redis:
            self.redis = await aioredis.from_url(self.redis_url)

    async def disconnect(self):
        if self.redis:
            await self.redis.close()

    async def save_task(self, task: Task) -> bool:
        try:
            await self.connect()
            task_data = self._serialize_task(task)
            key = f"{self.task_prefix}{task.id}"
            await self.redis.hset(key, mapping=task_data)
            await self.redis.expire(key, 86400 * 7)
            priority_score = task.config.priority.value * 1000 + int(time.time())
            queue_key = f"{self.queue_prefix}{task.config.task_type.value}"
            await self.redis.zadd(queue_key, {task.id: priority_score})
            return True
        except Exception as e:
            logger.error(f"Error saving task {task.id}: {e}")
            return False

    def _serialize_task(self, task: Task) -> Dict[str, str]:
        return {
            "id": task.id,
            "func_module": task.func.__module__,
            "func_name": task.func.__name__,
            "args": pickle.dumps(task.args).hex(),
            "kwargs": pickle.dumps(task.kwargs).hex(),
            "config": json.dumps(asdict(task.config)),
            "created_at": task.created_at.isoformat(),
            "status": task.status.value,
            "retries": str(task.retries),
            "user_id": task.user_id or "",
            "error_history": json.dumps(task.error_history),
        }

    async def get_task(self, task_id: str) -> Optional[Task]:
        try:
            await self.connect()
            key = f"{self.task_prefix}{task_id}"
            task_data = await self.redis.hgetall(key)
            if not task_data:
                return None
            return self._deserialize_task(task_data)
        except Exception as e:
            logger.error(f"Error getting task {task_id}: {e}")
            return None

    def _deserialize_task(self, task_data: Dict) -> Task:
        import importlib

        module = importlib.import_module(task_data[b"func_module"].decode())
        func = getattr(module, task_data[b"func_name"].decode())
        args = pickle.loads(bytes.fromhex(task_data[b"args"].decode()))
        kwargs = pickle.loads(bytes.fromhex(task_data[b"kwargs"].decode()))
        config_data = json.loads(task_data[b"config"].decode())
        config = TaskConfig(**config_data)
        return Task(
            id=task_data[b"id"].decode(),
            func=func,
            args=args,
            kwargs=kwargs,
            config=config,
            created_at=datetime.fromisoformat(task_data[b"created_at"].decode()),
            status=TaskStatus(task_data[b"status"].decode()),
            retries=int(task_data[b"retries"].decode()),
            user_id=task_data[b"user_id"].decode() or None,
            error_history=json.loads(task_data[b"error_history"].decode()),
        )

    async def update_task_status(self, task_id: str, status: TaskStatus) -> bool:
        try:
            await self.connect()
            key = f"{self.task_prefix}{task_id}"
            await self.redis.hset(key, "status", status.value)
            return True
        except Exception as e:
            logger.error(f"Error updating task status {task_id}: {e}")
            return False

    async def get_pending_tasks(self, limit: int = 100) -> List[Task]:
        await self.connect()
        tasks: List[Task] = []
        for task_type in TaskType:
            queue_key = f"{self.queue_prefix}{task_type.value}"
            ids = await self.redis.zrange(queue_key, 0, limit - 1)
            for tid in ids:
                t = await self.get_task(tid.decode())
                if t and t.status in {TaskStatus.PENDING, TaskStatus.RETRYING}:
                    tasks.append(t)
            if tasks:
                break
        return tasks

    async def cleanup_old_tasks(self, older_than_days: int = 7) -> int:
        await self.connect()
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        deleted = 0
        async for key in self.redis.scan_iter(f"{self.task_prefix}*"):
            created = await self.redis.hget(key, "created_at")
            if created and datetime.fromisoformat(created.decode()) < cutoff:
                await self.redis.delete(key)
                deleted += 1
        return deleted


class TaskWorker:
    def __init__(self, worker_id: str, storage: TaskStorage):
        self.worker_id = worker_id
        self.storage = storage
        self.running = False
        self.current_task: Optional[Task] = None
        self.stats = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "total_execution_time": 0,
            "started_at": None,
        }

    async def start(self):
        self.running = True
        self.stats["started_at"] = datetime.utcnow()
        logger.info(f"Worker {self.worker_id} started")
        while self.running:
            try:
                await self._process_next_task()
            except Exception as e:
                logger.error(f"Worker {self.worker_id} error: {e}")
                await asyncio.sleep(1)

    async def stop(self):
        self.running = False
        if self.current_task:
            logger.info(
                f"Worker {self.worker_id} stopping, current task: {self.current_task.id}"
            )

    async def _process_next_task(self):
        tasks = await self.storage.get_pending_tasks(limit=1)
        if not tasks:
            await asyncio.sleep(0.1)
            return
        task = tasks[0]
        await self._execute_task(task)

    async def _execute_task(self, task: Task):
        self.current_task = task
        start_time = time.time()
        start_memory = self._get_memory_usage()
        try:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            task.worker_id = self.worker_id
            await self.storage.update_task_status(task.id, TaskStatus.RUNNING)
            logger.info(f"Worker {self.worker_id} executing task {task.id}")
            if task.config.timeout:
                result = await asyncio.wait_for(
                    task.func(*task.args, **task.kwargs), timeout=task.config.timeout
                )
            else:
                result = await task.func(*task.args, **task.kwargs)
            execution_time = time.time() - start_time
            memory_used = self._get_memory_usage() - start_memory
            task.result = TaskResult(
                success=True,
                result=result,
                execution_time=execution_time,
                memory_used=memory_used,
                retries_used=task.retries,
            )
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            self.stats["tasks_completed"] += 1
            self.stats["total_execution_time"] += execution_time
            await self.storage.update_task_status(task.id, TaskStatus.COMPLETED)
            logger.info(f"Task {task.id} completed in {execution_time:.2f}s")
        except asyncio.TimeoutError:
            await self._handle_task_timeout(task)
        except Exception as e:
            await self._handle_task_error(task, e)
        finally:
            self.current_task = None

    async def _handle_task_error(self, task: Task, error: Exception):
        error_msg = str(error)
        task.error_history.append(f"Attempt {task.retries + 1}: {error_msg}")
        task.retries += 1
        logger.error(f"Task {task.id} failed (attempt {task.retries}): {error_msg}")
        if task.retries < task.config.max_retries:
            delay = task.config.retry_delay * (2 ** (task.retries - 1))
            task.status = TaskStatus.RETRYING
            await self.storage.update_task_status(task.id, TaskStatus.RETRYING)
            logger.info(f"Retrying task {task.id} in {delay}s")
            await asyncio.sleep(delay)
            await self.storage.save_task(task)
        else:
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.utcnow()
            task.result = TaskResult(
                success=False,
                error=error_msg,
                retries_used=task.retries,
            )
            self.stats["tasks_failed"] += 1
            await self.storage.update_task_status(task.id, TaskStatus.FAILED)
            logger.error(f"Task {task.id} permanently failed after {task.retries} retries")

    async def _handle_task_timeout(self, task: Task):
        task.status = TaskStatus.TIMEOUT
        task.completed_at = datetime.utcnow()
        task.result = TaskResult(
            success=False,
            error=f"Task timed out after {task.config.timeout}s",
        )
        self.stats["tasks_failed"] += 1
        await self.storage.update_task_status(task.id, TaskStatus.TIMEOUT)
        logger.error(f"Task {task.id} timed out")

    def _get_memory_usage(self) -> int:
        try:
            process = psutil.Process()
            return process.memory_info().rss // 1024 // 1024
        except Exception:
            return 0


class AdvancedTaskQueue:
    def __init__(self, concurrency: int = 3, storage: Optional[TaskStorage] = None, enable_monitoring: bool = True):
        self.concurrency = concurrency
        self.storage = storage or RedisTaskStorage()
        self.workers: List[TaskWorker] = []
        self.running = False
        self.enable_monitoring = enable_monitoring
        self.stats = {
            "started_at": None,
            "total_tasks_added": 0,
            "total_tasks_completed": 0,
            "total_tasks_failed": 0,
        }
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown")
        asyncio.create_task(self.stop())

    async def start(self):
        if self.running:
            return
        self.running = True
        self.stats["started_at"] = datetime.utcnow()
        for i in range(self.concurrency):
            worker_id = f"worker-{i+1}"
            worker = TaskWorker(worker_id, self.storage)
            self.workers.append(worker)
            asyncio.create_task(worker.start())
        logger.info(f"Task queue started with {self.concurrency} workers")
        if self.enable_monitoring:
            asyncio.create_task(self._monitoring_loop())

    async def stop(self, timeout: int = 30):
        if not self.running:
            return
        logger.info("Stopping task queue...")
        self.running = False
        stop_tasks = [worker.stop() for worker in self.workers]
        await asyncio.gather(*stop_tasks)
        deadline = time.time() + timeout
        while time.time() < deadline:
            running_workers = sum(1 for w in self.workers if w.current_task)
            if running_workers == 0:
                break
            await asyncio.sleep(0.1)
        if hasattr(self.storage, "disconnect"):
            await self.storage.disconnect()
        logger.info("Task queue stopped")

    async def add_task(self, func: Callable, *args, user_id: Optional[str] = None, config: Optional[TaskConfig] = None, **kwargs) -> str:
        task_id = str(uuid.uuid4())
        task_config = config or TaskConfig()
        task = Task(
            id=task_id,
            func=func,
            args=args,
            kwargs=kwargs,
            config=task_config,
            created_at=datetime.utcnow(),
            user_id=user_id,
        )
        success = await self.storage.save_task(task)
        if success:
            self.stats["total_tasks_added"] += 1
            logger.info(f"Task {task_id} added to queue")
            return task_id
        raise RuntimeError(f"Failed to save task {task_id}")

    async def get_task_status(self, task_id: str) -> Optional[Task]:
        return await self.storage.get_task(task_id)

    async def cancel_task(self, task_id: str) -> bool:
        task = await self.storage.get_task(task_id)
        if not task:
            return False
        if task.status in [TaskStatus.PENDING, TaskStatus.RETRYING]:
            await self.storage.update_task_status(task_id, TaskStatus.CANCELLED)
            logger.info(f"Task {task_id} cancelled")
            return True
        return False

    async def get_queue_stats(self) -> Dict[str, Any]:
        worker_stats = []
        for worker in self.workers:
            worker_stats.append(
                {
                    "id": worker.worker_id,
                    "current_task": worker.current_task.id if worker.current_task else None,
                    "tasks_completed": worker.stats["tasks_completed"],
                    "tasks_failed": worker.stats["tasks_failed"],
                    "total_execution_time": worker.stats["total_execution_time"],
                }
            )
        return {
            "running": self.running,
            "workers": len(self.workers),
            "worker_stats": worker_stats,
            "total_stats": self.stats,
            "uptime_seconds": (datetime.utcnow() - self.stats["started_at"]).total_seconds() if self.stats["started_at"] else 0,
        }

    async def _monitoring_loop(self):
        while self.running:
            try:
                await self.storage.cleanup_old_tasks(older_than_days=7)
                stats = await self.get_queue_stats()
                active_workers = sum(1 for w in stats["worker_stats"] if w["current_task"])
                logger.info(
                    f"Queue stats: {active_workers}/{len(self.workers)} workers active"
                )
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                await asyncio.sleep(60)


async def process_file_upload(file_path: str, user_id: str, file_size: int, original_name: str):
    logger.info(f"Processing file upload: {original_name} for user {user_id}")
    await asyncio.sleep(2)
    return {
        "status": "processed",
        "file_path": file_path,
        "processed_at": datetime.utcnow().isoformat(),
    }


async def send_notification(user_id: str, message: str, notification_type: str = "info"):
    logger.info(f"Sending {notification_type} notification to user {user_id}")
    await asyncio.sleep(0.5)
    return {"sent": True, "timestamp": datetime.utcnow().isoformat()}


async def cleanup_expired_files(older_than_days: int = 30):
    logger.info(f"Cleaning up files older than {older_than_days} days")
    await asyncio.sleep(5)
    return {"cleaned_files": 42, "freed_space_mb": 1024}


task_queue = AdvancedTaskQueue(concurrency=5)


async def add_file_processing_task(file_path: str, user_id: str, file_size: int, original_name: str) -> str:
    config = TaskConfig(
        task_type=TaskType.FILE_PROCESS,
        priority=TaskPriority.HIGH,
        timeout=300,
        max_retries=2,
    )
    return await task_queue.add_task(
        process_file_upload,
        file_path,
        user_id,
        file_size,
        original_name,
        user_id=user_id,
        config=config,
    )


async def add_notification_task(user_id: str, message: str) -> str:
    config = TaskConfig(
        task_type=TaskType.NOTIFICATION,
        priority=TaskPriority.NORMAL,
        timeout=30,
        max_retries=3,
    )
    return await task_queue.add_task(
        send_notification,
        user_id,
        message,
        user_id=user_id,
        config=config,
    )


async def add_cleanup_task() -> str:
    config = TaskConfig(
        task_type=TaskType.FILE_CLEANUP,
        priority=TaskPriority.LOW,
        timeout=600,
        max_retries=1,
    )
    return await task_queue.add_task(cleanup_expired_files, config=config)


async def start_task_queue():
    await task_queue.start()


async def stop_task_queue():
    await task_queue.stop()
