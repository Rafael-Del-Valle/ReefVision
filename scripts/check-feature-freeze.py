"""Fail when post-freeze commits add new ReefVision production modules.

Existing production files may still be modified for stabilization fixes. New tests,
documentation, scripts, and CI files remain allowed. The baseline and policy live in
.reefvision-feature-freeze.json.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True, slots=True)
class Change:
    status: str
    path: str
    previous_path: str | None = None


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def _load_policy(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read feature-freeze policy {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "reefvision-feature-freeze-v1":
        raise RuntimeError("Unsupported ReefVision feature-freeze policy")
    baseline = payload.get("baseline_sha")
    if not isinstance(baseline, str) or len(baseline.strip()) < 7:
        raise RuntimeError("Feature-freeze policy is missing baseline_sha")
    return payload


def _changes(baseline: str, head: str) -> list[Change]:
    _git("merge-base", "--is-ancestor", baseline, head)
    output = _git("diff", "--name-status", "--find-renames", f"{baseline}...{head}")
    changes: list[Change] = []
    for raw_line in output.splitlines():
        fields = raw_line.split("\t")
        if len(fields) < 2:
            continue
        status = fields[0]
        if status.startswith(("R", "C")) and len(fields) >= 3:
            changes.append(Change(status=status, previous_path=fields[1], path=fields[2]))
        else:
            changes.append(Change(status=status, path=fields[1]))
    return changes


def _starts_with(path: str, prefixes: list[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def _has_allowed_suffix(path: str, suffixes: list[str]) -> bool:
    return any(path.endswith(suffix) for suffix in suffixes)


def _blocked(change: Change, policy: dict[str, Any]) -> str | None:
    status_letter = change.status[:1]
    if status_letter not in {"A", "R", "C"}:
        return None

    path = PurePosixPath(change.path).as_posix()
    allowed_prefixes = [str(item) for item in policy.get("allowed_new_prefixes", [])]
    allowed_suffixes = [str(item) for item in policy.get("allowed_new_suffixes", [])]
    blocked_prefixes = [str(item) for item in policy.get("blocked_new_prefixes", [])]

    if path == ".reefvision-feature-freeze.json":
        return None
    if _starts_with(path, allowed_prefixes) or _has_allowed_suffix(path, allowed_suffixes):
        return None
    if _starts_with(path, blocked_prefixes):
        if path.startswith("apps/api/migrations/versions/"):
            return "new database migration added during the feature freeze"
        if status_letter in {"R", "C"}:
            return "production module rename/copy added during the feature freeze"
        return "new production module added during the feature freeze"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=Path(".reefvision-feature-freeze.json"))
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    try:
        policy = _load_policy(args.policy)
        baseline = str(policy["baseline_sha"])
        changes = _changes(baseline, args.head)
    except RuntimeError as exc:
        print(f"Feature-freeze check could not run: {exc}", file=sys.stderr)
        return 2

    violations = [
        {"status": change.status, "path": change.path, "reason": reason}
        for change in changes
        if (reason := _blocked(change, policy)) is not None
    ]
    report = {
        "schema": "reefvision-feature-freeze-report-v1",
        "baseline_sha": baseline,
        "head": _git("rev-parse", args.head).strip(),
        "change_count": len(changes),
        "violation_count": len(violations),
        "violations": violations,
        "passed": not violations,
    }
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if violations:
        print("ReefVision feature freeze failed:", file=sys.stderr)
        for item in violations:
            print(
                f"- {item['status']} {item['path']}: {item['reason']}",
                file=sys.stderr,
            )
        print(
            "Modify existing production files for fixes, or add tests/docs/scripts instead. "
            "Lift the freeze explicitly only after the release-candidate gates pass.",
            file=sys.stderr,
        )
        return 1

    print(
        f"ReefVision feature freeze passed: {len(changes)} post-baseline changes, "
        "no new production modules or migrations."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
