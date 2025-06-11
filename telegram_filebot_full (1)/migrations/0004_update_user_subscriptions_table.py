"""Migration script برای به‌روزرسانی جدول user_subscriptions"""
from alembic import op
import sqlalchemy as sa


def upgrade():
    # ایجاد enum ها
    subscription_status_enum = sa.Enum(
        'pending',
        'active',
        'expired',
        'cancelled',
        'suspended',
        'refunded',
        'trial',
        name='subscriptionstatus',
    )
    payment_status_enum = sa.Enum(
        'pending',
        'completed',
        'failed',
        'refunded',
        'partially_refunded',
        name='paymentstatus',
    )
    subscription_type_enum = sa.Enum('new', 'renewal', 'upgrade', 'downgrade', name='subscriptiontype')

    # افزودن ستون‌های جدید
    op.add_column('user_subscriptions', sa.Column('status', subscription_status_enum, default='pending'))
    op.add_column('user_subscriptions', sa.Column('subscription_type', subscription_type_enum, default='new'))
    op.add_column('user_subscriptions', sa.Column('payment_status', payment_status_enum, default='pending'))
    op.add_column('user_subscriptions', sa.Column('amount_paid', sa.Numeric(10, 2), default=0.00))
    op.add_column('user_subscriptions', sa.Column('auto_renewal', sa.Boolean, default=True))

    # اضافه کردن constraint ها
    op.create_check_constraint('valid_date_range', 'user_subscriptions', 'end_date > start_date')
    op.create_check_constraint('non_negative_amount', 'user_subscriptions', 'amount_paid >= 0')

    # ایجاد index ها
    op.create_index('idx_user_subscriptions_user_id', 'user_subscriptions', ['user_id'])
    op.create_index('idx_user_subscriptions_status', 'user_subscriptions', ['status'])
    op.create_index('idx_user_subscriptions_end_date', 'user_subscriptions', ['end_date'])


def downgrade():
    op.drop_index('idx_user_subscriptions_end_date', 'user_subscriptions')
    op.drop_index('idx_user_subscriptions_status', 'user_subscriptions')
    op.drop_index('idx_user_subscriptions_user_id', 'user_subscriptions')
    op.drop_constraint('non_negative_amount', 'user_subscriptions')
    op.drop_constraint('valid_date_range', 'user_subscriptions')
    op.drop_column('user_subscriptions', 'auto_renewal')
    op.drop_column('user_subscriptions', 'amount_paid')
    op.drop_column('user_subscriptions', 'payment_status')
    op.drop_column('user_subscriptions', 'subscription_type')
    op.drop_column('user_subscriptions', 'status')
