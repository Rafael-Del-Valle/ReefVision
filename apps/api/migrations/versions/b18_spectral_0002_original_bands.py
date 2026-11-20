"""Store original spectral band bindings, alignment and checked reflectance analyses."""

import sqlalchemy as sa
from alembic import op

revision = "b18_spectral_0002"
down_revision = "b18_integrated_0001"
branch_labels = None
depends_on = None


def _key():
    return sa.Column("id", sa.String(36), primary_key=True)


def _owner():
    return sa.Column(
        "project_id",
        sa.String(36),
        sa.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )


def _acquisition():
    return sa.Column(
        "acquisition_id",
        sa.String(36),
        sa.ForeignKey("multispectral_acquisitions.id", ondelete="CASCADE"),
        nullable=False,
    )


def _receipt():
    return (
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "multispectral_acquisitions",
        _key(),
        _owner(),
        *_receipt(),
        sa.UniqueConstraint("project_id", "content_sha256", name="uq_spectral_acquisition"),
    )
    op.create_table(
        "multispectral_band_bindings",
        _key(),
        _owner(),
        _acquisition(),
        sa.Column("image_id", sa.String(36), sa.ForeignKey("images.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("acquisition_id", "position", name="uq_spectral_position"),
        sa.UniqueConstraint("acquisition_id", "image_id", name="uq_spectral_image"),
    )
    op.create_table(
        "multispectral_indices",
        _key(),
        _owner(),
        _acquisition(),
        *_receipt(),
        sa.UniqueConstraint(
            "project_id", "acquisition_id", "content_sha256", name="uq_spectral_index"
        ),
    )


def downgrade() -> None:
    for name in (
        "multispectral_indices",
        "multispectral_band_bindings",
        "multispectral_acquisitions",
    ):
        op.drop_table(name)
