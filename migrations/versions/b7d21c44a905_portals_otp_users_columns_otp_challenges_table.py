"""portals + OTP: users columns, otp_challenges table

Revision ID: b7d21c44a905
Revises: 331451ca24f6
Create Date: 2026-11-16 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7d21c44a905'
down_revision = '331451ca24f6'
branch_labels = None
depends_on = None


def upgrade():
    # --- users: new OTP/portal columns ---------------------------------------
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_verified', sa.Boolean(),
                                      nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('failed_login_count', sa.Integer(),
                                      nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('locked_until', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('last_password_change_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('token_version', sa.Integer(),
                                      nullable=False, server_default='0'))
    # C4: existing users (seeded or created before OTP) must not be locked out.
    op.execute("UPDATE users SET email_verified = 1")

    # --- otp_challenges -------------------------------------------------------
    op.create_table('otp_challenges',
    sa.Column('id', sa.String(length=32), primary_key=True),
    sa.Column('user_id', sa.Integer(),
              sa.ForeignKey('users.id'), nullable=False),
    sa.Column('portal', sa.String(length=10), nullable=False),
    sa.Column('purpose', sa.String(length=20), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('resend_count', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.Column('locked_at', sa.DateTime(), nullable=True),
    sa.Column('ip_hash', sa.String(length=64), nullable=False),
    sa.Column('ua_hash', sa.String(length=64), nullable=False),
    sa.Column('destination', sa.String(length=255), nullable=True),
    sa.Column('consumed', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index('ix_otp_challenges_user_id_purpose', 'otp_challenges', ['user_id', 'purpose'])
    op.create_index('ix_otp_challenges_expires_at', 'otp_challenges', ['expires_at'])


def downgrade():
    op.drop_index('ix_otp_challenges_expires_at', table_name='otp_challenges')
    op.drop_index('ix_otp_challenges_user_id_purpose', table_name='otp_challenges')
    op.drop_table('otp_challenges')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('token_version')
        batch_op.drop_column('last_password_change_at')
        batch_op.drop_column('locked_until')
        batch_op.drop_column('failed_login_count')
        batch_op.drop_column('email_verified')
