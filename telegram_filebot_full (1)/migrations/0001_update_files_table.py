"""Migration script برای به‌روزرسانی جدول files"""
from alembic import op
import sqlalchemy as sa


def upgrade():
    # ایجاد enum ها
    file_status_enum = sa.Enum(
        'uploading',
        'processing',
        'ready',
        'error',
        'deleted',
        'quarantined',
        name='filestatus',
    )
    file_type_enum = sa.Enum(
        'image',
        'video',
        'audio',
        'document',
        'archive',
        'other',
        name='filetype',
    )
    compression_type_enum = sa.Enum('none', 'gzip', 'lz4', 'zstd', name='compressiontype')

    # افزودن ستون‌های جدید
    op.add_column('files', sa.Column('sanitized_file_name', sa.String(255)))
    op.add_column('files', sa.Column('file_type', file_type_enum, default='other'))
    op.add_column('files', sa.Column('mime_type', sa.String(100)))
    op.add_column('files', sa.Column('file_extension', sa.String(10)))
    op.add_column('files', sa.Column('relative_path', sa.String(500)))
    op.add_column('files', sa.Column('compressed_size', sa.BigInteger))
    op.add_column('files', sa.Column('compression_type', compression_type_enum, default='none'))
    op.add_column('files', sa.Column('file_hash_md5', sa.String(32)))
    op.add_column('files', sa.Column('file_hash_sha256', sa.String(64)))
    op.add_column('files', sa.Column('is_virus_scanned', sa.Boolean, default=False))
    op.add_column('files', sa.Column('virus_scan_result', sa.String(50)))
    op.add_column('files', sa.Column('download_count', sa.Integer, default=0))
    op.add_column('files', sa.Column('last_downloaded_at', sa.DateTime))
    op.add_column('files', sa.Column('access_expires_at', sa.DateTime))
    op.add_column('files', sa.Column('telegram_file_id', sa.String(200)))
    op.add_column('files', sa.Column('telegram_file_unique_id', sa.String(200)))
    op.add_column('files', sa.Column('status', file_status_enum, default='ready'))
    op.add_column('files', sa.Column('metadata', sa.JSON))
    op.add_column('files', sa.Column('tags', sa.JSON))
    op.add_column('files', sa.Column('description', sa.Text))
    op.add_column('files', sa.Column('updated_at', sa.DateTime))
    op.add_column('files', sa.Column('deleted_at', sa.DateTime))
    op.add_column('files', sa.Column('processed_at', sa.DateTime))
    op.add_column('files', sa.Column('upload_duration', sa.Float))
    op.add_column('files', sa.Column('processing_duration', sa.Float))

    # تغییر نوع ستون file_size
    op.alter_column('files', 'file_size', type_=sa.BigInteger)

    # ایجاد index‌ها
    op.create_index('idx_files_user_id', 'files', ['user_id'])
    op.create_index('idx_files_created_at', 'files', ['created_at'])
    op.create_index('idx_files_status', 'files', ['status'])
    op.create_index('idx_files_file_type', 'files', ['file_type'])
    op.create_index('idx_files_user_status', 'files', ['user_id', 'status'])
    op.create_index('idx_files_hash_md5', 'files', ['file_hash_md5'])
    op.create_index('idx_files_download_token', 'files', ['download_token'])
    op.create_index('idx_files_telegram_file_id', 'files', ['telegram_file_id'])
    op.create_index('idx_files_deleted_at', 'files', ['deleted_at'])

    # ایجاد constraint‌ها
    op.create_check_constraint('positive_file_size', 'files', 'file_size > 0')
    op.create_check_constraint('non_negative_download_count', 'files', 'download_count >= 0')


def downgrade():
    # حذف constraint‌ها و index‌ها
    op.drop_constraint('positive_file_size', 'files')
    op.drop_constraint('non_negative_download_count', 'files')
    op.drop_index('idx_files_user_id', 'files')
    op.drop_index('idx_files_created_at', 'files')
    op.drop_index('idx_files_status', 'files')
    op.drop_index('idx_files_file_type', 'files')
    op.drop_index('idx_files_user_status', 'files')
    op.drop_index('idx_files_hash_md5', 'files')
    op.drop_index('idx_files_download_token', 'files')
    op.drop_index('idx_files_telegram_file_id', 'files')
    op.drop_index('idx_files_deleted_at', 'files')

    # حذف ستون‌های اضافه شده
    op.drop_column('files', 'sanitized_file_name')
    op.drop_column('files', 'file_type')
    op.drop_column('files', 'mime_type')
    op.drop_column('files', 'file_extension')
    op.drop_column('files', 'relative_path')
    op.drop_column('files', 'compressed_size')
    op.drop_column('files', 'compression_type')
    op.drop_column('files', 'file_hash_md5')
    op.drop_column('files', 'file_hash_sha256')
    op.drop_column('files', 'is_virus_scanned')
    op.drop_column('files', 'virus_scan_result')
    op.drop_column('files', 'download_count')
    op.drop_column('files', 'last_downloaded_at')
    op.drop_column('files', 'access_expires_at')
    op.drop_column('files', 'telegram_file_id')
    op.drop_column('files', 'telegram_file_unique_id')
    op.drop_column('files', 'status')
    op.drop_column('files', 'metadata')
    op.drop_column('files', 'tags')
    op.drop_column('files', 'description')
    op.drop_column('files', 'updated_at')
    op.drop_column('files', 'deleted_at')
    op.drop_column('files', 'processed_at')
    op.drop_column('files', 'upload_duration')
    op.drop_column('files', 'processing_duration')

