import asyncio
import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.config import config
from app.core.exceptions import FileOperationError
from app.models.file import File, FileStatus
from app.models.user_subscription import SubscriptionStatus, UserSubscription


logger = logging.getLogger(__name__)


class CleanupResult(Enum):
    """Result of a single file cleanup operation."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    BACKED_UP = "backed_up"


@dataclass
class CleanupStats:
    """Statistics gathered during cleanup."""

    total_files_checked: int = 0
    files_deleted: int = 0
    files_backed_up: int = 0
    files_failed: int = 0
    files_skipped: int = 0
    total_size_freed: int = 0
    execution_time: float = 0
    errors: List[str] | None = None

    def __post_init__(self) -> None:  # pragma: no cover - simple default init
        if self.errors is None:
            self.errors = []


class AdvancedCleanupService:
    """Advanced service for cleaning up expired and orphaned files."""

    def __init__(self) -> None:
        self.backup_enabled: bool = getattr(config, "CLEANUP_BACKUP_ENABLED", True)
        self.backup_dir: Path = Path(
            getattr(config, "CLEANUP_BACKUP_DIR", "./backups")
        )
        self.expiry_days: int = getattr(config, "FILE_EXPIRY_DAYS", 30)
        self.batch_size: int = getattr(config, "CLEANUP_BATCH_SIZE", 100)

        if self.backup_enabled:
            self.backup_dir.mkdir(parents=True, exist_ok=True)

    async def cleanup_expired_files(
        self,
        expiry_days: int | None = None,
        dry_run: bool = False,
        user_ids: List[str] | None = None,
    ) -> CleanupStats:
        """Clean up files that belong to expired or inactive users."""

        start_time = datetime.utcnow()
        stats = CleanupStats()

        expiry = expiry_days or self.expiry_days
        cutoff_date = datetime.utcnow() - timedelta(days=expiry)

        logger.info(
            "Starting cleanup: expiry_days=%s dry_run=%s", expiry, dry_run
        )

        async with get_db() as session:
            async for batch in self._get_expired_files_batch(
                session, cutoff_date, user_ids
            ):
                batch_stats = await self._process_file_batch(session, batch, dry_run)
                self._merge_stats(stats, batch_stats)
                logger.info(
                    "Processed batch of %s files. Deleted so far: %s",
                    len(batch),
                    stats.files_deleted,
                )

        stats.execution_time = (datetime.utcnow() - start_time).total_seconds()
        logger.info(
            "Cleanup finished in %.2fs - deleted: %s, freed: %.2f MB",
            stats.execution_time,
            stats.files_deleted,
            stats.total_size_freed / (1024 * 1024),
        )
        return stats

    async def _get_expired_files_batch(
        self,
        session: AsyncSession,
        cutoff_date: datetime,
        user_ids: List[str] | None,
    ):
        offset = 0
        while True:
            query = (
                select(File, UserSubscription)
                .outerjoin(
                    UserSubscription,
                    and_(
                        UserSubscription.user_id == File.user_id,
                        UserSubscription.status == SubscriptionStatus.ACTIVE,
                    ),
                )
                .where(
                    File.created_at < cutoff_date,
                    File.status != FileStatus.DELETED,
                    File.deleted_at.is_(None),
                )
            )

            if user_ids:
                query = query.where(File.user_id.in_(user_ids))

            query = query.where(
                or_(
                    UserSubscription.id.is_(None),
                    UserSubscription.status != SubscriptionStatus.ACTIVE,
                    UserSubscription.end_date < datetime.utcnow(),
                )
            )

            result = await session.execute(query.offset(offset).limit(self.batch_size))
            batch = result.all()
            if not batch:
                break

            yield [row[0] for row in batch]
            offset += len(batch)

            if offset > 10000:
                logger.warning("Reached maximum file limit per cleanup run")
                break

    async def _process_file_batch(
        self, session: AsyncSession, files: List[File], dry_run: bool
    ) -> CleanupStats:
        stats = CleanupStats(total_files_checked=len(files))
        for file in files:
            try:
                result = await self._process_single_file(session, file, dry_run)
                if result == CleanupResult.SUCCESS:
                    stats.files_deleted += 1
                    stats.total_size_freed += file.file_size or 0
                elif result == CleanupResult.BACKED_UP:
                    stats.files_backed_up += 1
                elif result == CleanupResult.SKIPPED:
                    stats.files_skipped += 1
                elif result == CleanupResult.FAILED:
                    stats.files_failed += 1
            except Exception as e:  # pragma: no cover - log errors
                logger.error("Failed to process file %s: %s", file.id, e)
                stats.files_failed += 1
                stats.errors.append(f"File {file.id}: {e}")

        if not dry_run:
            try:
                await session.commit()
            except Exception as e:  # pragma: no cover - db commit failures
                await session.rollback()
                logger.error("Failed to commit batch: %s", e)
                stats.errors.append(f"Batch commit failed: {e}")

        return stats

    async def _process_single_file(
        self, session: AsyncSession, file: File, dry_run: bool
    ) -> CleanupResult:
        if dry_run:
            logger.info("[DRY RUN] Would delete %s", file.original_file_name)
            return CleanupResult.SUCCESS

        try:
            if not os.path.exists(file.storage_path):
                await self._soft_delete_file(session, file)
                logger.info("File missing on disk, removed from DB: %s", file.id)
                return CleanupResult.SUCCESS

            if self.backup_enabled:
                if not await self._backup_file(file):
                    logger.warning("Backup failed for file %s", file.id)
                    return CleanupResult.FAILED

            await self._delete_file_from_disk(file.storage_path)
            await self._soft_delete_file(session, file)
            logger.info("Deleted file %s", file.original_file_name)
            return CleanupResult.SUCCESS

        except FileOperationError as exc:  # pragma: no cover - pass-through
            logger.error("File operation failed for %s: %s", file.id, exc)
            return CleanupResult.FAILED
        except Exception as exc:  # pragma: no cover - catch all
            logger.error("Unexpected error processing %s: %s", file.id, exc)
            return CleanupResult.FAILED

    async def _backup_file(self, file: File) -> bool:
        if not os.path.exists(file.storage_path):
            return True

        try:
            backup_date = datetime.utcnow().strftime("%Y-%m-%d")
            backup_subdir = self.backup_dir / backup_date
            backup_subdir.mkdir(parents=True, exist_ok=True)

            file_hash = hashlib.md5(file.id.encode()).hexdigest()[:8]
            backup_filename = f"{file_hash}_{file.original_file_name}"
            backup_path = backup_subdir / backup_filename

            await asyncio.get_running_loop().run_in_executor(
                None, shutil.copy2, file.storage_path, backup_path
            )

            metadata = {
                "file_id": file.id,
                "user_id": file.user_id,
                "original_path": file.storage_path,
                "original_name": file.original_file_name,
                "file_size": file.file_size,
                "created_at": file.created_at.isoformat(),
                "backup_date": datetime.utcnow().isoformat(),
            }

            metadata_path = backup_path.with_suffix(".json")
            metadata_json = json.dumps(metadata, ensure_ascii=False)
            await asyncio.get_running_loop().run_in_executor(
                None, metadata_path.write_text, metadata_json
            )

            logger.debug("File backed up to %s", backup_path)
            return True
        except Exception as exc:  # pragma: no cover - log errors
            logger.error("Backup failed for %s: %s", file.id, exc)
            return False

    async def _delete_file_from_disk(self, file_path: str) -> None:
        try:
            await asyncio.get_running_loop().run_in_executor(None, os.remove, file_path)
        except FileNotFoundError:
            pass
        except PermissionError as exc:
            raise FileOperationError(f"Permission denied: {file_path}") from exc
        except OSError as exc:
            raise FileOperationError(f"OS error deleting file: {file_path}") from exc

    async def _soft_delete_file(self, session: AsyncSession, file: File) -> None:
        file.deleted_at = datetime.utcnow()
        file.status = FileStatus.DELETED
        session.add(file)

    def _merge_stats(self, main: CleanupStats, batch: CleanupStats) -> None:
        main.total_files_checked += batch.total_files_checked
        main.files_deleted += batch.files_deleted
        main.files_backed_up += batch.files_backed_up
        main.files_failed += batch.files_failed
        main.files_skipped += batch.files_skipped
        main.total_size_freed += batch.total_size_freed
        if batch.errors:
            main.errors.extend(batch.errors)

    async def cleanup_orphaned_files(self) -> CleanupStats:
        stats = CleanupStats()
        upload_dir = Path(config.UPLOAD_DIR)
        if not upload_dir.exists():
            return stats

        async with get_db() as session:
            result = await session.execute(
                select(File.storage_path).where(File.deleted_at.is_(None))
            )
            db_paths = {row[0] for row in result.all()}

            for file_path in upload_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                stats.total_files_checked += 1
                if str(file_path) not in db_paths:
                    try:
                        if self.backup_enabled:
                            await self._backup_orphaned_file(file_path)
                        size = file_path.stat().st_size
                        file_path.unlink()
                        stats.files_deleted += 1
                        stats.total_size_freed += size
                        logger.info("Deleted orphaned file %s", file_path)
                    except Exception as exc:
                        stats.files_failed += 1
                        stats.errors.append(f"Failed to delete {file_path}: {exc}")

        return stats

    async def _backup_orphaned_file(self, file_path: Path) -> None:
        try:
            orphan_dir = self.backup_dir / "orphaned" / datetime.utcnow().strftime(
                "%Y-%m-%d"
            )
            orphan_dir.mkdir(parents=True, exist_ok=True)
            backup_path = orphan_dir / file_path.name
            await asyncio.get_running_loop().run_in_executor(
                None, shutil.copy2, file_path, backup_path
            )
        except Exception as exc:  # pragma: no cover - log errors
            logger.error("Failed to backup orphaned file %s: %s", file_path, exc)

    async def cleanup_empty_directories(self) -> int:
        removed = 0
        upload_dir = Path(config.UPLOAD_DIR)
        if not upload_dir.exists():
            return removed

        for dir_path in sorted(
            upload_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True
        ):
            if dir_path.is_dir() and dir_path != upload_dir:
                try:
                    if not any(dir_path.iterdir()):
                        dir_path.rmdir()
                        removed += 1
                        logger.debug("Removed empty directory %s", dir_path)
                except OSError:
                    pass

        return removed

    async def get_cleanup_report(self) -> Dict[str, object]:
        async with get_db() as session:
            total_files = await session.scalar(select(func.count(File.id)))
            cutoff_date = datetime.utcnow() - timedelta(days=self.expiry_days)
            expired_query = (
                select(func.count(File.id), func.sum(File.file_size))
                .select_from(File)
                .outerjoin(
                    UserSubscription,
                    and_(
                        UserSubscription.user_id == File.user_id,
                        UserSubscription.status == SubscriptionStatus.ACTIVE,
                    ),
                )
                .where(
                    File.created_at < cutoff_date,
                    File.status != FileStatus.DELETED,
                    File.deleted_at.is_(None),
                    or_(
                        UserSubscription.id.is_(None),
                        UserSubscription.status != SubscriptionStatus.ACTIVE,
                        UserSubscription.end_date < datetime.utcnow(),
                    ),
                )
            )
            result = await session.execute(expired_query)
            expired_count, expired_size = result.first()

            return {
                "total_files": total_files,
                "expired_files": expired_count or 0,
                "expired_size_mb": round((expired_size or 0) / (1024 * 1024), 2),
                "cutoff_date": cutoff_date.isoformat(),
                "expiry_days": self.expiry_days,
                "backup_enabled": self.backup_enabled,
                "estimated_cleanup_time": f"{(expired_count or 0) * 0.1:.1f} seconds",
            }


cleanup_service = AdvancedCleanupService()


async def scheduled_cleanup() -> CleanupStats:
    """Run cleanup in background task."""

    stats = await cleanup_service.cleanup_expired_files()
    if stats.files_deleted > 0 or stats.errors:
        await send_cleanup_report_to_admins(stats)
    return stats


async def send_cleanup_report_to_admins(stats: CleanupStats) -> None:
    """Placeholder for sending report to administrators."""

    logger.info(
        "Cleanup report: deleted=%s backed_up=%s failed=%s freed=%.2f MB",
        stats.files_deleted,
        stats.files_backed_up,
        stats.files_failed,
        stats.total_size_freed / (1024 * 1024),
    )


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="File Cleanup Service")
    parser.add_argument("--dry-run", action="store_true", help="Run without deleting")
    parser.add_argument("--expiry-days", type=int, default=30, help="File expiry")
    parser.add_argument("--orphaned", action="store_true", help="Clean orphaned")
    parser.add_argument("--report", action="store_true", help="Show report")

    args = parser.parse_args()

    if args.report:
        report = await cleanup_service.get_cleanup_report()
        print(json.dumps(report, indent=2, default=str))
        return

    if args.orphaned:
        stats = await cleanup_service.cleanup_orphaned_files()
        print(f"Orphaned cleanup: {stats.files_deleted} files deleted")
        return

    stats = await cleanup_service.cleanup_expired_files(
        expiry_days=args.expiry_days, dry_run=args.dry_run
    )
    print(
        f"Cleanup completed: {stats.files_deleted} files deleted, {stats.total_size_freed / (1024 * 1024):.2f} MB freed"
    )


if __name__ == "__main__":  # pragma: no cover - manual execution
    asyncio.run(main())

