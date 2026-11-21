"""Regression for cross-branch Alembic audits with different revision IDs.

Distinct revision IDs are not collisions, but integrating their two histories
without a reviewed linear migration would still leave divergent heads.
"""

import json
import subprocess
import sys
from pathlib import Path


def test_cross_branch_audit_flags_distinct_branch_only_revisions(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )

    git("init", "-q")
    git("config", "user.name", "ReefVision Test")
    git("config", "user.email", "ci@example.invalid")
    git("config", "commit.gpgsign", "false")
    migrations = tmp_path / "apps" / "api" / "migrations" / "versions"
    migrations.mkdir(parents=True)
    (migrations / "0001_root.py").write_text('revision = "0001"\ndown_revision = None\n')
    git("add", ".")
    git("commit", "-q", "-m", "root")
    git("branch", "science")
    git("branch", "review")

    git("switch", "-q", "science")
    (migrations / "0002_science.py").write_text(
        'revision = "0002_science"\ndown_revision = "0001"\n'
    )
    git("add", ".")
    git("commit", "-q", "-m", "science")

    git("switch", "-q", "review")
    (migrations / "0002_review.py").write_text('revision = "0002_review"\ndown_revision = "0001"\n')
    git("add", ".")
    git("commit", "-q", "-m", "review")

    audit = Path(__file__).resolve().parents[4] / "scripts" / "audit-alembic-collisions.py"
    result = subprocess.run(
        [sys.executable, str(audit), "science", "review"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["collision_count"] == 0
    assert report["invalid_branch_graph_count"] == 0
    assert report["branch_only_revision_count"] == 2
    assert report["requires_reviewed_data_preserving_reconciliation"] is True
    assert {
        item["revision"]: (item["present_in"], item["absent_in"])
        for item in report["branch_only_revisions"]
    } == {
        "0002_science": (["science"], ["review"]),
        "0002_review": (["review"], ["science"]),
    }

    # The same real Git branches must also reject an orphaned revision:
    # distinct IDs alone do not prove that either applied history is valid.
    (migrations / "0002_review.py").write_text(
        'revision = "0002_review"\ndown_revision = "deleted_parent"\n'
    )
    git("add", ".")
    git("commit", "-q", "-m", "orphaned review migration")
    invalid = subprocess.run(
        [sys.executable, str(audit), "science", "review"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid.returncode == 2, invalid.stderr
    invalid_report = json.loads(invalid.stdout)
    assert invalid_report["invalid_branch_graph_count"] == 1
    assert invalid_report["invalid_branch_graphs"]["review"] == [
        "missing parent deleted_parent for 0002_review"
    ]
    assert invalid_report["refs"]["review"]["commit"] != report["refs"]["review"]["commit"]
