"""Join the four independent, additive 1.5 research migrations."""

revision = "b15_integrated_0001"
down_revision = ("b15_model_0001", "b15_review_0001", "b15_study_0001", "b15_field_0001")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
