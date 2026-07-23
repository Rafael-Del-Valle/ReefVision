from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast


def _load_checker() -> ModuleType:
    script = Path(__file__).parents[4] / "scripts" / "check-feature-freeze.py"
    specification = importlib.util.spec_from_file_location(
        "reefvision_feature_freeze_checker",
        script,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def _policy() -> dict[str, Any]:
    return {
        "schema": "reefvision-feature-freeze-v1",
        "baseline_sha": "abc1234",
        "allowed_new_prefixes": [
            ".github/",
            "docs/",
            "scripts/",
            "apps/api/reefvision/tests/",
            "apps/api/reefvision/testing/",
            "apps/web/tests/",
        ],
        "allowed_new_suffixes": [
            ".test.ts",
            ".test.tsx",
            ".spec.ts",
            ".spec.tsx",
        ],
        "blocked_new_prefixes": [
            "apps/api/migrations/versions/",
            "apps/api/reefvision/",
            "apps/web/src/",
            "apps/web/src-tauri/src/",
        ],
    }


def test_feature_freeze_blocks_new_production_modules_and_migrations() -> None:
    checker = _load_checker()
    change_type = cast(Any, checker.Change)
    blocked = cast(Any, checker._blocked)

    production_reason = blocked(
        change_type(
            status="A",
            path="apps/api/reefvision/services/new_feature.py",
        ),
        _policy(),
    )
    migration_reason = blocked(
        change_type(
            status="A",
            path="apps/api/migrations/versions/0035_new_feature.py",
        ),
        _policy(),
    )

    assert (
        production_reason
        == "new production module added during the feature freeze"
    )
    assert migration_reason == "new database migration added during the feature freeze"


def test_feature_freeze_allows_fixes_tests_docs_scripts_and_ci() -> None:
    checker = _load_checker()
    change_type = cast(Any, checker.Change)
    blocked = cast(Any, checker._blocked)
    policy = _policy()

    allowed = [
        change_type(status="M", path="apps/api/reefvision/services/existing.py"),
        change_type(
            status="A",
            path="apps/api/reefvision/tests/test_regression.py",
        ),
        change_type(
            status="A",
            path="apps/web/src/features/a/Panel.test.tsx",
        ),
        change_type(status="A", path="docs/STABILIZATION.md"),
        change_type(status="A", path="scripts/check-release.py"),
        change_type(status="A", path=".github/workflows/stabilization.yml"),
        change_type(status="A", path=".reefvision-feature-freeze.json"),
    ]

    assert [blocked(change, policy) for change in allowed] == [None] * len(allowed)


def test_feature_freeze_blocks_production_renames_and_copies() -> None:
    checker = _load_checker()
    change_type = cast(Any, checker.Change)
    blocked = cast(Any, checker._blocked)

    for status in ("R100", "C100"):
        reason = blocked(
            change_type(
                status=status,
                previous_path="apps/api/reefvision/services/old.py",
                path="apps/api/reefvision/services/new.py",
            ),
            _policy(),
        )
        assert (
            reason
            == "production module rename/copy added during the feature freeze"
        )
