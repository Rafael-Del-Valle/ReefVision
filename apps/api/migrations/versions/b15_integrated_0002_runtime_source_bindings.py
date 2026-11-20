"""Recover the source bindings omitted by early applied 1.5 runtime schemas."""

import hashlib
import json

import sqlalchemy as sa
from alembic import op
from alembic.util import CommandError

revision = "b15_integrated_0002"
down_revision = "b15_integrated_0001"
branch_labels = None
depends_on = None

_TABLE = "model_runtime_selections"
_BINDINGS = "source_id_map_json"
_EARLY_COLUMNS = {"id", "project_id", "model_id", "snapshot_json", "content_sha256", "created_at"}


def _recovery(detail: str) -> CommandError:
    return CommandError(
        f"Cannot reconcile the early model runtime selections ({detail}). "
        "Open a copy of the verified pre-upgrade backup with its original ReefVision build "
        "and export the project with its signed model review and original import provenance."
    )


def upgrade() -> None:
    context = op.get_context()
    if context.as_sql:
        if str(context.opts.get("starting_rev", "")).startswith("b15_"):
            raise _recovery("the existing 1.5 database requires an online upgrade")
        return

    connection = op.get_bind()
    columns = {item["name"] for item in sa.inspect(connection).get_columns(_TABLE)}
    if _BINDINGS in columns:
        return
    if columns != _EARLY_COLUMNS:
        raise _recovery("unrecognized table columns")

    selections = sa.table(
        _TABLE,
        sa.column("id", sa.String),
        sa.column("project_id", sa.String),
        sa.column("model_id", sa.String),
        sa.column("content_sha256", sa.String),
        sa.column("snapshot_json", sa.JSON),
        sa.column(_BINDINGS, sa.JSON),
    )
    packages = sa.table(
        "project_exchange_packages",
        sa.column("project_id"),
        sa.column("direction"),
        sa.column("status"),
        sa.column("options_json", sa.JSON),
    )
    records = sa.select(
        selections.c.id,
        selections.c.project_id,
        selections.c.model_id,
        selections.c.content_sha256,
        selections.c.snapshot_json,
    )
    copied: dict[str, dict[str, str]] = {}
    for row in connection.execute(records).mappings():
        try:
            snapshot = row["snapshot_json"]
            encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if hashlib.sha256(encoded).hexdigest() != row["content_sha256"]:
                raise _recovery("signed receipt digest mismatch")
            source_project, source_model = (
                snapshot["source_project_id"],
                snapshot["source_model_id"],
            )
            if source_project == row["project_id"] and source_model == row["model_id"]:
                continue
            classes = {value for value in snapshot.get("class_mapping", {}).values() if value}
            identifiers = {source_project, source_model, *classes}
            sources = connection.scalars(
                sa.select(packages.c.options_json).where(
                    packages.c.project_id == row["project_id"],
                    packages.c.direction == "import",
                    packages.c.status == "complete",
                )
            )
            candidates: list[dict[str, str]] = []
            for options in sources:
                aliases = options.get("origin_id_map") or options.get("id_map", {})
                if (
                    aliases.get(source_project) == row["project_id"]
                    and aliases.get(source_model) == row["model_id"]
                    and identifiers <= aliases.keys()
                ):
                    candidate = {key: aliases[key] for key in identifiers}
                    if candidate not in candidates:
                        candidates.append(candidate)
            if len(candidates) != 1:
                raise _recovery("unproven source IDs for a copied receipt")
            copied[row["id"]] = candidates[0]
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise _recovery("invalid model review or import provenance") from exc

    op.add_column(_TABLE, sa.Column(_BINDINGS, sa.JSON, nullable=False, server_default="{}"))
    for selection_id, mapping in copied.items():
        connection.execute(
            sa.update(selections)
            .where(selections.c.id == selection_id)
            .values(source_id_map_json=mapping)
        )


def downgrade() -> None:
    # The published predecessor already expects this column. Back up and restore
    # the original profile to return to the earlier six-column prototype.
    pass
