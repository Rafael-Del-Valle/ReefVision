"""Join image adjustments, reviewed taxonomy and recorded audio on the 1.7 schema."""

revision = "b18_integrated_0001"
down_revision = ("b18_adjust_0001", "b18_taxon_0001", "b18_audio_0001")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
