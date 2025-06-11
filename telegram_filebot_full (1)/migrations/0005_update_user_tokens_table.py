"""Migration script برای به‌روزرسانی جدول user_tokens"""
from alembic import op
import sqlalchemy as sa


def upgrade():
    # ایجاد enum ها
    token_type_enum = sa.Enum('access', 'refresh', 'api', 'temporary', 'admin', name='tokentype')
    token_status_enum = sa.Enum('active', 'expired', 'revoked', 'suspended', name='tokenstatus')
    device_type_enum = sa.Enum('mobile', 'desktop', 'web', 'bot', 'api_client', 'unknown', name='devicetype')

    # تغییر طول token_hash
    op.alter_column('user_tokens', 'token_hash', type_=sa.String(64))

    # افزودن ستون‌های جدید
    op.add_column('user_tokens', sa.Column('token_type', token_type_enum, default='access'))
    op.add_column('user_tokens', sa.Column('status', token_status_enum, default='active'))
    op.add_column('user_tokens', sa.Column('device_type', device_type_enum, default='unknown'))
    op.add_column('user_tokens', sa.Column('access_count', sa.Integer, default=0))
    op.add_column('user_tokens', sa.Column('security_score', sa.Integer, default=100))

    # اضافه کردن constraint ها
    op.create_check_constraint('valid_expiry_date', 'user_tokens', 'expires_at > created_at')
    op.create_check_constraint('non_negative_access_count', 'user_tokens', 'access_count >= 0')
    op.create_unique_constraint('unique_token_hash', 'user_tokens', ['token_hash'])

    # ایجاد index ها
    op.create_index('idx_user_tokens_expires_at', 'user_tokens', ['expires_at'])
    op.create_index('idx_user_tokens_status', 'user_tokens', ['status'])
    op.create_index('idx_user_tokens_type', 'user_tokens', ['token_type'])


def downgrade():
    op.drop_index('idx_user_tokens_type', 'user_tokens')
    op.drop_index('idx_user_tokens_status', 'user_tokens')
    op.drop_index('idx_user_tokens_expires_at', 'user_tokens')
    op.drop_constraint('unique_token_hash', 'user_tokens')
    op.drop_constraint('non_negative_access_count', 'user_tokens')
    op.drop_constraint('valid_expiry_date', 'user_tokens')
    op.drop_column('user_tokens', 'security_score')
    op.drop_column('user_tokens', 'access_count')
    op.drop_column('user_tokens', 'device_type')
    op.drop_column('user_tokens', 'status')
    op.drop_column('user_tokens', 'token_type')
    op.alter_column('user_tokens', 'token_hash', type_=sa.String())
