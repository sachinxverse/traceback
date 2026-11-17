"""embedding provenance: embedding_model + embedding_dim on reports and report_images

Issue 1: vectors from different embedding backends must never be compared.
Every stored vector now records the model that produced it and its
dimension; matching filters on the model id before any cosine.

Revision ID: c4e5f6a7b890
Revises: b7d21c44a905
Create Date: 2026-11-17 19:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c4e5f6a7b890'
down_revision = 'b7d21c44a905'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('reports', sa.Column('embedding_model', sa.String(80), nullable=True))
    op.add_column('reports', sa.Column('embedding_dim', sa.Integer(), nullable=True))
    op.add_column('report_images', sa.Column('embedding_model', sa.String(80), nullable=True))
    op.add_column('report_images', sa.Column('embedding_dim', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('report_images', 'embedding_dim')
    op.drop_column('report_images', 'embedding_model')
    op.drop_column('reports', 'embedding_dim')
    op.drop_column('reports', 'embedding_model')
