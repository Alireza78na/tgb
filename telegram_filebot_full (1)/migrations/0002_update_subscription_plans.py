"""Migration script برای به‌روزرسانی جدول subscription_plans"""
from alembic import op
import sqlalchemy as sa


def upgrade():
    # ایجاد enum ها
    plan_type_enum = sa.Enum(
        'free', 'basic', 'premium', 'enterprise', 'custom', name='plantype'
    )
    billing_cycle_enum = sa.Enum(
        'daily', 'weekly', 'monthly', 'yearly', 'lifetime', name='billingcycle'
    )

    # افزودن ستون‌های جدید
    op.add_column(
        'subscription_plans',
        sa.Column('display_name', sa.String(150), nullable=False, server_default='')
    )
    op.add_column('subscription_plans', sa.Column('description', sa.Text))
    op.add_column(
        'subscription_plans',
        sa.Column('plan_type', plan_type_enum, default='free')
    )
    op.add_column(
        'subscription_plans',
        sa.Column('max_file_size_mb', sa.Integer, default=50)
    )
    op.add_column(
        'subscription_plans',
        sa.Column('max_downloads_per_day', sa.Integer, default=100)
    )
    op.add_column(
        'subscription_plans',
        sa.Column('max_api_calls_per_hour', sa.Integer, default=1000)
    )
    op.add_column(
        'subscription_plans', sa.Column('currency', sa.String(3), default='USD')
    )
    op.add_column(
        'subscription_plans',
        sa.Column('billing_cycle', billing_cycle_enum, default='monthly')
    )
    op.add_column(
        'subscription_plans', sa.Column('trial_days', sa.Integer, default=0)
    )
    op.add_column('subscription_plans', sa.Column('features', sa.Text))
    op.add_column('subscription_plans', sa.Column('restrictions', sa.Text))
    op.add_column(
        'subscription_plans', sa.Column('is_visible', sa.Boolean, default=True)
    )
    op.add_column(
        'subscription_plans', sa.Column('is_popular', sa.Boolean, default=False)
    )
    op.add_column(
        'subscription_plans', sa.Column('sort_order', sa.Integer, default=0)
    )
    op.add_column(
        'subscription_plans',
        sa.Column(
            'created_at',
            sa.DateTime,
            server_default=sa.text('CURRENT_TIMESTAMP')
        )
    )
    op.add_column('subscription_plans', sa.Column('updated_at', sa.DateTime))
    op.add_column('subscription_plans', sa.Column('deleted_at', sa.DateTime))

    # تغییر نوع ستون price
    op.alter_column(
        'subscription_plans', 'price', type_=sa.Numeric(10, 2), server_default='0.00'
    )

    # اضافه کردن constraints
    op.create_check_constraint(
        'positive_storage', 'subscription_plans', 'max_storage_mb > 0'
    )
    op.create_check_constraint(
        'positive_files', 'subscription_plans', 'max_files > 0'
    )
    op.create_check_constraint(
        'positive_file_size', 'subscription_plans', 'max_file_size_mb > 0'
    )
    op.create_check_constraint(
        'non_negative_price', 'subscription_plans', 'price >= 0'
    )
    op.create_check_constraint(
        'positive_expiry', 'subscription_plans', 'expiry_days > 0'
    )
    op.create_check_constraint(
        'non_negative_trial', 'subscription_plans', 'trial_days >= 0'
    )
    op.create_check_constraint(
        'non_negative_sort', 'subscription_plans', 'sort_order >= 0'
    )

    # ایجاد index ها
    op.create_index(
        'idx_subscription_plans_active', 'subscription_plans', ['is_active']
    )
    op.create_index(
        'idx_subscription_plans_visible', 'subscription_plans', ['is_visible']
    )
    op.create_index(
        'idx_subscription_plans_type', 'subscription_plans', ['plan_type']
    )
    op.create_index(
        'idx_subscription_plans_price', 'subscription_plans', ['price']
    )
    op.create_index(
        'idx_subscription_plans_sort', 'subscription_plans', ['sort_order']
    )
    op.create_index(
        'idx_subscription_plans_deleted', 'subscription_plans', ['deleted_at']
    )

    # ایجاد unique constraint
    op.create_unique_constraint('unique_plan_name', 'subscription_plans', ['name'])


def downgrade():
    # حذف constraint‌ها و index‌ها
    op.drop_constraint('unique_plan_name', 'subscription_plans')
    op.drop_index('idx_subscription_plans_active', 'subscription_plans')
    op.drop_index('idx_subscription_plans_visible', 'subscription_plans')
    op.drop_index('idx_subscription_plans_type', 'subscription_plans')
    op.drop_index('idx_subscription_plans_price', 'subscription_plans')
    op.drop_index('idx_subscription_plans_sort', 'subscription_plans')
    op.drop_index('idx_subscription_plans_deleted', 'subscription_plans')
    op.drop_constraint('positive_storage', 'subscription_plans')
    op.drop_constraint('positive_files', 'subscription_plans')
    op.drop_constraint('positive_file_size', 'subscription_plans')
    op.drop_constraint('non_negative_price', 'subscription_plans')
    op.drop_constraint('positive_expiry', 'subscription_plans')
    op.drop_constraint('non_negative_trial', 'subscription_plans')
    op.drop_constraint('non_negative_sort', 'subscription_plans')

    # حذف ستون‌های اضافه شده
    op.drop_column('subscription_plans', 'display_name')
    op.drop_column('subscription_plans', 'description')
    op.drop_column('subscription_plans', 'plan_type')
    op.drop_column('subscription_plans', 'max_file_size_mb')
    op.drop_column('subscription_plans', 'max_downloads_per_day')
    op.drop_column('subscription_plans', 'max_api_calls_per_hour')
    op.drop_column('subscription_plans', 'currency')
    op.drop_column('subscription_plans', 'billing_cycle')
    op.drop_column('subscription_plans', 'trial_days')
    op.drop_column('subscription_plans', 'features')
    op.drop_column('subscription_plans', 'restrictions')
    op.drop_column('subscription_plans', 'is_visible')
    op.drop_column('subscription_plans', 'is_popular')
    op.drop_column('subscription_plans', 'sort_order')
    op.drop_column('subscription_plans', 'created_at')
    op.drop_column('subscription_plans', 'updated_at')
    op.drop_column('subscription_plans', 'deleted_at')
