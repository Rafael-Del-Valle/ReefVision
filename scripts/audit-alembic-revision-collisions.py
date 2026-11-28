#!/usr/bin/env python3
"""Fail-closed Alembic revision collision audit; never modifies migrations or data."""

import argparse
import ast
import hashlib
import json
import os
import re
import stat
import unicodedata
from collections import defaultdict
from pathlib import Path


def revision_from_source(path: Path, source: bytes | None = None) -> str | None:
    """Parse a single source snapshot without importing migration side effects."""
    if source is None:
        source = path.read_bytes()
    tree = ast.parse(source, filename=str(path))
    revisions = []
    for node in tree.body:
        if (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "revision"
        ):
            raise ValueError(f"{path}: augmented revision assignment is not permitted")
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                isinstance(name, ast.Name) and name.id == "revision"
                for target in targets
                for name in ast.walk(target)
            ):
                # A destructured target can bind revision to only part of a
                # literal string (e.g. revision, other = "ab"). Reject it
                # even when no separate revision assignment exists.
                if len(targets) != 1 or not (
                    isinstance(targets[0], ast.Name) and targets[0].id == "revision"
                ):
                    raise ValueError(f"{path}: revision must be a literal string assignment")
                value = node.value
                if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                    raise ValueError(f"{path}: revision must be a literal string")
                revisions.append(value.value)
    # Deleting the revision binding is also a mutation: a later import may
    # fail or observe a different value. Reject deletion at any depth.
    for statement in ast.walk(tree):
        if isinstance(statement, ast.Delete) and any(
            isinstance(name, ast.Name) and name.id == "revision"
            for target in statement.targets
            for name in ast.walk(target)
        ):
            raise ValueError(f"{path}: deletion of revision is not permitted")
    # Nested writes can change the effective revision at import time. Never
    # execute migrations to discover that value; reject ambiguous source.
    for statement in ast.walk(tree):
        if statement in tree.body:
            continue
        if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if any(
                isinstance(name, ast.Name) and name.id == "revision"
                for target in targets
                for name in ast.walk(target)
            ):
                raise ValueError(f"{path}: nested revision assignment is not permitted")
    # Loop and context-manager targets bind names without Assign nodes. A
    # migration that rebinds revision this way cannot be audited statically.
    for statement in ast.walk(tree):
        targets = []
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            targets = [statement.target]
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            targets = [item.optional_vars for item in statement.items if item.optional_vars]
        elif isinstance(statement, ast.ExceptHandler) and statement.name == "revision":
            raise ValueError(f"{path}: exception handler rebinds revision")
        if any(
            isinstance(name, ast.Name) and name.id == "revision"
            for target in targets
            for name in ast.walk(target)
        ):
            raise ValueError(f"{path}: implicit revision rebinding is not permitted")
    # Comprehension targets are implicit bindings too. Although their scope is
    # local in Python 3, reject them consistently with nested function writes:
    # the auditor must not infer runtime revision semantics from executable code.
    for statement in ast.walk(tree):
        if isinstance(statement, ast.comprehension) and any(
            isinstance(name, ast.Name) and name.id == "revision"
            for name in ast.walk(statement.target)
        ):
            raise ValueError(f"{path}: comprehension rebinds revision")
    # Imports and declarations also bind names without an assignment node.
    # Reject them rather than assuming a previously parsed literal survives.
    for statement in ast.walk(tree):
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            # Star imports may introduce an arbitrary revision binding at runtime.
            # Never execute imported modules to determine their exported names.
            if isinstance(statement, ast.ImportFrom) and any(
                alias.name == "*" for alias in statement.names
            ):
                raise ValueError(f"{path}: wildcard import may rebind revision")
            if any(
                (alias.asname or alias.name.split(".")[0]) == "revision"
                for alias in statement.names
            ):
                raise ValueError(f"{path}: import rebinds revision")
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if statement.name == "revision":
                raise ValueError(f"{path}: declaration rebinds revision")
        elif isinstance(statement, getattr(ast, "TypeAlias", ())) and any(
            isinstance(name, ast.Name) and name.id == "revision"
            for name in ast.walk(statement.name)
        ):
            raise ValueError(f"{path}: type alias rebinds revision")
    # Parameter bindings can shadow revision inside executable nested scopes.
    # Reject these rather than interpreting nested runtime behavior as a
    # trustworthy, static migration identifier. This includes lambda,
    # positional-only, keyword-only, vararg and kwarg parameters.
    for statement in ast.walk(tree):
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            parameters = statement.args
            names = [
                *parameters.posonlyargs,
                *parameters.args,
                *parameters.kwonlyargs,
            ]
            if any(parameter.arg == "revision" for parameter in names) or any(
                parameter is not None and parameter.arg == "revision"
                for parameter in (parameters.vararg, parameters.kwarg)
            ):
                raise ValueError(f"{path}: parameter shadows revision")
    # Structural pattern matching can bind revision without an Assign node.
    # Capture names occur in MatchAs/MatchStar/MatchMapping patterns.
    for statement in ast.walk(tree):
        if isinstance(statement, (ast.MatchAs, ast.MatchStar)) and statement.name == "revision":
            raise ValueError(f"{path}: pattern rebinds revision")
        if isinstance(statement, ast.MatchMapping) and statement.rest == "revision":
            raise ValueError(f"{path}: pattern rebinds revision")
    # Aliased imports provide the same dynamic namespace access as direct
    # builtins calls. Reject dangerous from-imports and track module aliases
    # without importing or executing any migration code.
    builtins_names = {"builtins"}
    for statement in ast.walk(tree):
        if isinstance(statement, ast.Import):
            builtins_names.update(
                alias.asname or "builtins" for alias in statement.names if alias.name == "builtins"
            )
        elif (
            isinstance(statement, ast.ImportFrom)
            and statement.module == "builtins"
            and any(
                alias.name in {"exec", "eval", "globals", "locals", "vars"}
                for alias in statement.names
            )
        ):
            raise ValueError(f"{path}: dynamic builtins import may rebind revision")
    # Dynamic execution can mutate the module namespace after a literal
    # revision assignment. Static inspection cannot establish its outcome.
    # Namespace-introspection calls can also expose mutable dictionaries that
    # rewrite revision indirectly. Reject these calls without executing code.
    # Reject it without running any migration code or imported modules.
    for statement in ast.walk(tree):
        if (
            isinstance(statement, ast.Call)
            and isinstance(statement.func, ast.Name)
            and statement.func.id in {"exec", "eval", "globals", "locals", "vars"}
        ) or (
            isinstance(statement, ast.Call)
            and isinstance(statement.func, ast.Attribute)
            and statement.func.attr in {"exec", "eval", "globals", "locals", "vars"}
            and isinstance(statement.func.value, ast.Name)
            and statement.func.value.id in builtins_names
        ):
            raise ValueError(f"{path}: dynamic execution may rebind revision")
    # Reflective access can retrieve dynamic execution from builtins without
    # a direct exec/eval call. Never evaluate migration source to resolve it.
    for statement in ast.walk(tree):
        if (
            isinstance(statement, ast.Call)
            and isinstance(statement.func, ast.Name)
            and statement.func.id == "getattr"
            and statement.args
            and isinstance(statement.args[0], ast.Name)
            and statement.args[0].id in builtins_names
        ) or (
            isinstance(statement, ast.Attribute)
            and statement.attr == "__dict__"
            and isinstance(statement.value, ast.Name)
            and statement.value.id in builtins_names
        ):
            raise ValueError(f"{path}: reflective builtins access may rebind revision")
    if len(revisions) > 1:
        raise ValueError(f"{path}: multiple revision assignments")
    return revisions[0] if revisions else None


def _literal_revision_links(
    path: Path, source: bytes, *, field: str, allow_missing: bool = False
) -> tuple[str, ...]:
    """Read literal Alembic links without importing executable migrations."""
    tree = ast.parse(source, filename=str(path))
    assignments: list[tuple[str, ...]] = []
    permitted_targets: set[int] = set()
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        matching = [
            target
            for target in targets
            if any(isinstance(node, ast.Name) and node.id == field for node in ast.walk(target))
        ]
        if not matching:
            continue
        if len(targets) != 1 or not isinstance(targets[0], ast.Name) or targets[0].id != field:
            raise ValueError(f"{path}: {field} must use a direct literal assignment")
        permitted_targets.add(id(targets[0]))
        value = statement.value
        if isinstance(value, ast.Constant) and value.value is None:
            parents: tuple[str, ...] = ()
        elif isinstance(value, ast.Constant) and isinstance(value.value, str):
            parents = (value.value,)
        elif isinstance(value, (ast.Tuple, ast.List)) and value.elts:
            if not all(
                isinstance(element, ast.Constant) and isinstance(element.value, str)
                for element in value.elts
            ):
                raise ValueError(f"{path}: {field} revisions must be literal strings")
            parents = tuple(element.value for element in value.elts)
        else:
            raise ValueError(f"{path}: {field} must be a literal parent or None")
        if any(not parent or parent != parent.strip() for parent in parents):
            raise ValueError(f"{path}: noncanonical {field}")
        if len(parents) != len(set(parents)):
            raise ValueError(f"{path}: duplicate {field} parent")
        assignments.append(parents)

    # A nested assignment, loop target, deletion or walrus expression can
    # replace the literal after import. Do not execute it to find out.
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and node.id == field
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and id(node) not in permitted_targets
        ):
            raise ValueError(f"{path}: dynamic {field} rebinding")
        # A literal list can still change through a method call, an alias,
        # or a subscript without rebinding the metadata name itself. Strict
        # graph metadata is declarative; even a benign read is outside this
        # static contract. Never execute the migration to infer its outcome.
        if isinstance(node, ast.Name) and node.id == field and isinstance(node.ctx, ast.Load):
            raise ValueError(f"{path}: executable reference to {field} is unsupported")
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name == field:
            raise ValueError(f"{path}: pattern rebinds {field}")
        if isinstance(node, ast.MatchMapping) and node.rest == field:
            raise ValueError(f"{path}: pattern rebinds {field}")
        if isinstance(node, ast.ExceptHandler) and node.name == field:
            raise ValueError(f"{path}: exception rebinds {field}")
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == field
        ):
            raise ValueError(f"{path}: declaration rebinds {field}")
        if isinstance(node, (ast.Import, ast.ImportFrom)) and any(
            (alias.asname or alias.name.split(".")[0]) == field for alias in node.names
        ):
            raise ValueError(f"{path}: import rebinds {field}")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            parameters = node.args
            named = [
                *parameters.posonlyargs,
                *parameters.args,
                *parameters.kwonlyargs,
            ]
            if any(arg.arg == field for arg in named) or any(
                arg is not None and arg.arg == field
                for arg in (parameters.vararg, parameters.kwarg)
            ):
                raise ValueError(f"{path}: parameter shadows {field}")
        if isinstance(node, getattr(ast, "TypeAlias", ())) and any(
            isinstance(name, ast.Name) and name.id == field for name in ast.walk(node.name)
        ):
            raise ValueError(f"{path}: type alias rebinds {field}")
    if allow_missing and not assignments:
        return ()
    if len(assignments) != 1:
        raise ValueError(f"{path}: exactly one literal {field} is required")
    return assignments[0]


def parent_revisions_from_source(path: Path, source: bytes) -> tuple[str, ...]:
    """Read parent links for the supported dependency-free, unlabeled lineage."""
    parents = _literal_revision_links(path, source, field="down_revision")
    # Alembic also orders revisions by depends_on. A parent-only graph cannot
    # establish complete ancestry if those independent edges are present.
    if _literal_revision_links(path, source, field="depends_on", allow_missing=True):
        raise ValueError(f"{path}: depends_on links are unsupported by parent-only verification")
    # Alembic branch labels share a namespace with revision IDs and can
    # collide with each other. This parent-only audit does not verify labels.
    if _literal_revision_links(path, source, field="branch_labels", allow_missing=True):
        raise ValueError(f"{path}: branch_labels are unsupported by parent-only verification")
    return parents


def audit_parent_graph(entries: list[tuple[str, tuple[str, ...]]]) -> dict:
    """Check a single complete migration directory as an isolated DAG."""
    parents: dict[str, tuple[str, ...]] = {}
    duplicates: set[str] = set()
    for revision, links in entries:
        if revision in parents:
            duplicates.add(revision)
        else:
            parents[revision] = links

    all_parents = {parent for links in parents.values() for parent in links}
    missing = sorted(all_parents - parents.keys())
    bases = sorted(revision for revision, links in parents.items() if not links)
    heads = sorted(parents.keys() - all_parents)
    colors: dict[str, int] = {}
    cycles: set[str] = set()

    def visit(revision: str, stack: tuple[str, ...]) -> None:
        state = colors.get(revision, 0)
        if state == 1:
            cycles.update(stack[stack.index(revision) :])
            return
        if state == 2:
            return
        colors[revision] = 1
        for parent in parents[revision]:
            if parent in parents:
                visit(parent, (*stack, revision))
        colors[revision] = 2

    for revision in sorted(parents):
        visit(revision, ())
    consistent = (
        len(bases) == 1 and len(heads) == 1 and not missing and not cycles and not duplicates
    )
    return {
        "consistent": consistent,
        "root_revisions": bases,
        "head_revisions": heads,
        "missing_parent_revisions": missing,
        "cycle_revisions": sorted(cycles),
        "duplicate_revision_ids": sorted(duplicates),
    }


def ancestry_fingerprints(
    entries: list[tuple[str, tuple[str, ...]]], source_hashes: dict[str, str]
) -> dict[str, str]:
    """Fingerprint each source and its complete ancestry in a validated DAG."""
    parents = dict(entries)
    fingerprints: dict[str, str] = {}

    def visit(revision: str) -> str:
        if revision not in fingerprints:
            payload = [
                revision,
                source_hashes[revision],
                [[parent, visit(parent)] for parent in sorted(parents[revision])],
            ]
            fingerprints[revision] = hashlib.sha256(
                json.dumps(payload, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
        return fingerprints[revision]

    for revision in sorted(parents):
        visit(revision)
    return fingerprints


def classify_ancestry(values: list[str | None]) -> str:
    if None in values:
        return "unverified_graph"
    return "identical_history" if len(set(values)) == 1 else "divergent_history"


def _canonical_graph_revision(value: str) -> bool:
    """Limit strict ancestry evidence to ReefVision's durable revision tokens."""
    return re.fullmatch(r"[A-Za-z0-9_]{1,32}", value) is not None and value not in {
        "base",
        "head",
        "heads",
    }


def revision_manifest(
    entries: list[tuple[str, str, tuple[str, ...]]],
    source_sha256: dict[str, str],
    ancestry_by_path: dict[str, str],
) -> list[dict]:
    """Retain every source, including unique heads and duplicate identifiers."""
    return [
        {
            "revision": revision,
            "path": path,
            "parent_revisions": list(parents),
            "source_sha256": source_sha256[path],
            "ancestry_sha256": ancestry_by_path.get(path),
        }
        for revision, path, parents in entries
    ]


def compare_revision_manifests(
    manifests: dict[str, list[dict]], graphs: dict[str, dict]
) -> list[dict]:
    """Summarize pairwise overlap without inferring an automatic remapping."""
    comparisons = []
    roots = sorted(manifests)
    for index, left_root in enumerate(roots):
        for right_root in roots[index + 1 :]:
            left = {row["revision"]: row for row in manifests[left_root]}
            right = {row["revision"]: row for row in manifests[right_root]}
            shared = left.keys() & right.keys()
            verified = graphs[left_root]["consistent"] and graphs[right_root]["consistent"]
            identical = divergent = frontier = None
            if verified:
                common = {
                    revision
                    for revision in shared
                    if left[revision]["ancestry_sha256"] == right[revision]["ancestry_sha256"]
                }
                common_parents = {
                    parent for revision in common for parent in left[revision]["parent_revisions"]
                }
                identical = sorted(common)
                divergent = sorted(shared - common)
                frontier = sorted(common - common_parents)
            comparisons.append(
                {
                    "left_root": left_root,
                    "right_root": right_root,
                    "ancestry_verified": verified,
                    "left_only_revisions": sorted(left.keys() - right.keys()),
                    "right_only_revisions": sorted(right.keys() - left.keys()),
                    "shared_revision_ids": sorted(shared),
                    "identical_history_revisions": identical,
                    "divergent_history_revisions": divergent,
                    "common_ancestry_frontier": frontier,
                }
            )
    return comparisons


def _checked_path_stat(path: Path, *, ancestor: bool = False) -> os.stat_result:
    """Reject filesystem redirects before resolving or walking a migration root."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        if ancestor:
            raise ValueError(f"Migration directory has a symbolic-link ancestor: {path}")
        raise ValueError(f"Migration tree contains a symbolic link: {path}")
    if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError(f"Migration tree contains a Windows reparse point: {path}")
    return info


def _portable_entry_name(name: str) -> bool:
    """Conservative Windows checkout rules, independent of the audit host."""
    if name.endswith((" ", ".")) or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name):
        return False
    stem = name.split(".", 1)[0].rstrip(" ").upper()
    return not (
        stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        or re.fullmatch(r"(?:COM|LPT)[1-9\u00b9\u00b2\u00b3]", stem)
    )


def _migration_sources(root: Path, *, verify_parent_graph: bool = False) -> list[Path]:
    """Inventory ordinary Python files without following directory redirects."""
    pending = [root]
    sources = []
    while pending:
        directory = pending.pop()
        portable_names: set[str] = set()
        for entry in directory.iterdir():
            info = _checked_path_stat(entry)
            if verify_parent_graph:
                if not _portable_entry_name(entry.name):
                    raise ValueError(f"{entry}: nonportable migration tree entry name")
                if entry.name.casefold().endswith(".py") and not entry.name.endswith(".py"):
                    raise ValueError(f"{entry}: nonportable migration source extension")
                portable_name = unicodedata.normalize("NFC", entry.name.casefold())
                if portable_name in portable_names:
                    raise ValueError(f"{entry}: case-colliding migration source name or tree entry")
                portable_names.add(portable_name)
            if entry.match("*.py"):
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError(f"Migration source is not a regular file: {entry}")
                sources.append(entry)
            elif stat.S_ISDIR(info.st_mode):
                pending.append(entry)
    return sorted(sources)


def audit(roots: list[Path], *, verify_parent_graph: bool = False) -> dict:
    by_revision: dict[str, list[str]] = defaultdict(list)
    source_sha256: dict[str, str] = {}
    migration_files = 0
    seen_roots: set[Path] = set()
    parent_graphs: dict[str, dict] = {}
    ancestry_by_path: dict[str, str] = {}
    revision_manifests: dict[str, list[dict]] = {}
    for root in roots:
        # A repeated directory must not manufacture a revision collision.
        # Check each path component before resolving so symlinked ancestors
        # cannot silently redirect the audit outside the requested tree.
        absolute_root = root.absolute()
        try:
            for part in reversed((absolute_root, *absolute_root.parents)):
                _checked_path_stat(part, ancestor=True)
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise ValueError(f"Migration directory missing: {root}") from exc
        canonical_root = root.resolve(strict=False)
        if canonical_root in seen_roots:
            raise ValueError(f"Migration directory specified more than once: {root}")
        if any(
            canonical_root in previous.parents or previous in canonical_root.parents
            for previous in seen_roots
        ):
            raise ValueError(f"Migration directories overlap: {root}")
        seen_roots.add(canonical_root)
        if not root.is_dir():
            raise ValueError(f"Migration directory missing: {root}")
        # Inventory every entry before reading migration bytes. pathlib.rglob
        # can omit redirected directories; Windows junctions are not symlinks.
        sources = _migration_sources(root, verify_parent_graph=verify_parent_graph)
        root_entries: list[tuple[str, tuple[str, ...]]] = []
        root_paths: dict[str, str] = {}
        root_manifest_entries: list[tuple[str, str, tuple[str, ...]]] = []
        for path in sources:
            if not stat.S_ISREG(_checked_path_stat(path).st_mode):
                raise ValueError(f"Migration source is not a regular file: {path}")
            if path.name == "__init__.py":
                continue
            # Match the packaged Alembic configuration: nonrecursive source
            # discovery, with editor-lock and __init__ prefixes excluded.
            # Keep the legacy recursive inventory available for diagnostics.
            if verify_parent_graph and (
                path.parent != root or path.name.startswith((".#", "__init__"))
            ):
                raise ValueError(
                    f"{path}: unsupported strict graph migration source location or name"
                )
            migration_files += 1
            source = path.read_bytes()
            if verify_parent_graph:
                # AST parsing alone accepts some sources that Python cannot
                # compile (e.g. a module-level return). Check the same bytes
                # without executing imports, migration functions or DDL.
                compile(source, str(path), "exec", dont_inherit=True)
            revision = revision_from_source(path, source)
            if revision is None:
                raise ValueError(f"{path}: missing literal revision assignment")
            if not revision.strip() or revision != revision.strip():
                raise ValueError(f"{path}: noncanonical revision")
            if verify_parent_graph:
                if not _canonical_graph_revision(revision):
                    raise ValueError(f"{path}: unsupported strict graph revision identifier")
                parents = parent_revisions_from_source(path, source)
                if any(not _canonical_graph_revision(parent) for parent in parents):
                    raise ValueError(f"{path}: unsupported strict graph parent identifier")
                root_entries.append((revision, parents))
                root_paths[revision] = str(path)
                root_manifest_entries.append((revision, str(path), parents))
            by_revision[revision].append(str(path))
            source_sha256[str(path)] = hashlib.sha256(source).hexdigest()
        if verify_parent_graph:
            graph = audit_parent_graph(root_entries)
            parent_graphs[str(root)] = graph
            if graph["consistent"]:
                fingerprints = ancestry_fingerprints(
                    root_entries,
                    {revision: source_sha256[path] for revision, path in root_paths.items()},
                )
                ancestry_by_path.update(
                    {path: fingerprints[revision] for revision, path in root_paths.items()}
                )
            revision_manifests[str(root)] = revision_manifest(
                root_manifest_entries, source_sha256, ancestry_by_path
            )
    if migration_files == 0:
        raise ValueError("No migration revision files found")
    collisions = {
        revision: paths for revision, paths in sorted(by_revision.items()) if len(paths) > 1
    }
    report = {
        "safe_to_reconcile_automatically": False,
        "revision_count": len(by_revision),
        "collisions": collisions,
        "collision_source_sha256": {
            revision: {path: source_sha256[path] for path in paths}
            for revision, paths in collisions.items()
        },
        # Common byte-identical history is still a duplicate identifier, but
        # reviewers need to distinguish it from independently changed source.
        # A source difference is not itself proof of different DDL.
        "collision_source_relationship": {
            revision: (
                "byte_identical"
                if len({source_sha256[path] for path in paths}) == 1
                else "source_differs"
            )
            for revision, paths in collisions.items()
        },
        "collision_free": not bool(collisions),
    }
    if verify_parent_graph:
        # Identical descendant source does not establish shared ancestry after
        # an earlier collision. Invalid graphs provide no ancestry evidence.
        report["collision_ancestry_sha256"] = {
            revision: {path: ancestry_by_path.get(path) for path in paths}
            for revision, paths in collisions.items()
        }
        report["collision_ancestry_relationship"] = {
            revision: classify_ancestry([ancestry_by_path.get(path) for path in paths])
            for revision, paths in collisions.items()
        }
        report["parent_graphs"] = parent_graphs
        report["revision_manifests"] = revision_manifests
        report["root_comparisons"] = compare_revision_manifests(revision_manifests, parent_graphs)
        report["parent_graph_consistent"] = all(
            graph["consistent"] for graph in parent_graphs.values()
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("migration_dirs", nargs="+", type=Path)
    parser.add_argument("--verify-parent-graph", action="store_true")
    args = parser.parse_args()
    try:
        report = audit(args.migration_dirs, verify_parent_graph=args.verify_parent_graph)
    except (OSError, SyntaxError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["collision_free"] or (
        args.verify_parent_graph and not report["parent_graph_consistent"]
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
