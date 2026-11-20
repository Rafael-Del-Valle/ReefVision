"""Preserve original recordings, sample evidence, and reviewed alignments."""

import sqlalchemy as sa
from alembic import op

revision = "b18_audio_0001"
down_revision = "b17_monitor_0003"
branch_labels = None
depends_on = None


def _owner_columns():
    return (
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )


def _asset_id():
    return sa.Column(
        "asset_id",
        sa.String(36),
        sa.ForeignKey("bioacoustic_assets.id", ondelete="CASCADE"),
        nullable=False,
    )


def _created():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)


def upgrade() -> None:
    op.create_table(
        "bioacoustic_assets",
        *_owner_columns(),
        sa.Column("original_asset_id", sa.String(36), nullable=False),
        sa.Column("original_project_id", sa.String(36), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("managed_path", sa.String(700), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sample_rate_hz", sa.Integer(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("channel_count", sa.Integer(), nullable=False),
        sa.Column("bits_per_sample", sa.Integer(), nullable=False),
        _created(),
        sa.UniqueConstraint("project_id", "sha256", name="uq_audio_original"),
    )
    op.create_index(
        "ix_audio_assets_project", "bioacoustic_assets", ["project_id", "created_at", "id"]
    )
    op.create_table(
        "bioacoustic_clock_anchors",
        *_owner_columns(),
        _asset_id(),
        sa.Column("anchor_json", sa.JSON(), nullable=False),
        sa.Column("anchor_sha256", sa.String(64), nullable=False),
        sa.Column("author", sa.String(200), nullable=False),
        _created(),
        sa.UniqueConstraint("asset_id", "anchor_sha256", name="uq_audio_anchor_content"),
    )
    op.create_index(
        "ix_audio_anchors_owner",
        "bioacoustic_clock_anchors",
        ["project_id", "asset_id", "created_at", "id"],
    )
    op.create_table(
        "bioacoustic_proposals",
        *_owner_columns(),
        _asset_id(),
        sa.Column("proposal_json", sa.JSON(), nullable=False),
        sa.Column("proposal_sha256", sa.String(64), nullable=False),
        sa.Column("author", sa.String(200), nullable=False),
        _created(),
    )
    op.create_index(
        "ix_audio_proposals_owner",
        "bioacoustic_proposals",
        ["project_id", "asset_id", "created_at", "id"],
    )
    op.create_table(
        "bioacoustic_reviews",
        *_owner_columns(),
        sa.Column(
            "proposal_id",
            sa.String(36),
            sa.ForeignKey("bioacoustic_proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reviewer", sa.String(200), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("proposal_id", "revision", name="uq_audio_review_revision"),
    )
    op.create_index(
        "ix_audio_reviews_owner", "bioacoustic_reviews", ["project_id", "proposal_id", "revision"]
    )
    op.create_table(
        "bioacoustic_reports",
        *_owner_columns(),
        _asset_id(),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("report_sha256", sa.String(64), nullable=False),
        _created(),
        sa.UniqueConstraint("asset_id", "report_sha256", name="uq_audio_report_content"),
    )
    op.create_index(
        "ix_audio_reports_owner",
        "bioacoustic_reports",
        ["project_id", "asset_id", "created_at", "id"],
    )


def downgrade() -> None:
    for table in (
        "bioacoustic_reports",
        "bioacoustic_reviews",
        "bioacoustic_proposals",
        "bioacoustic_clock_anchors",
        "bioacoustic_assets",
    ):
        op.drop_table(table)
