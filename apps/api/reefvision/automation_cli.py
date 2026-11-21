"""Console and packaged entry points for local automation."""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
from collections.abc import Sequence
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from reefvision_sdk import AutomationError, ReefVision


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        prog="reefvision",
        description="Use a local ReefVision project. Exit 3 requests human review.",
    )
    where = cli.add_mutually_exclusive_group(required=True)
    where.add_argument(
        "--profile",
        type=Path,
        help="Absolute local profile directory for offline, headless operation",
    )
    where.add_argument("--api-url", help="Running local API URL shown in Help → Automation API")
    cli.add_argument(
        "--timeout",
        type=float,
        default=3600,
        help="Maximum seconds to wait for the local operation",
    )
    group = cli.add_subparsers(dest="group", required=True)
    projects = group.add_parser("project").add_subparsers(dest="verb", required=True)
    projects.add_parser("create").add_argument("name")
    projects.add_parser("open").add_argument("project")
    workflows = group.add_parser("workflow").add_subparsers(dest="verb", required=True)
    for name in ("plan", "run"):
        sub = workflows.add_parser(name)
        sub.add_argument("project")
        sub.add_argument("graph_id")
        sub.add_argument("--sha256", required=True, help="Saved graph SHA-256")
        if name == "run":
            sub.add_argument(
                "--inputs", type=Path, help="Optional workflow inputs as a JSON object"
            )
    for name in ("status", "resume"):
        sub = workflows.add_parser(name)
        sub.add_argument("project")
        sub.add_argument("run_id")
        if name == "resume":
            sub.add_argument("--node", required=True)
            sub.add_argument("--reviewer", required=True)
            sub.add_argument("--note", required=True)
    infer = group.add_parser(
        "infer", help="Infer unverified proposals using a pinned local checkpoint and originals"
    )
    infer.add_argument("project")
    infer.add_argument("--model", required=True)
    infer.add_argument("--sha256", required=True, help="Checkpoint SHA-256")
    infer.add_argument("--image", action="append", required=True, metavar="UUID=SHA256")
    infer.add_argument("--device", choices=["cpu", "cuda", "auto"], default="auto")
    benchmark = group.add_parser(
        "benchmark", help="Compare reviewed model choices on pinned independent units"
    )
    benchmark.add_argument("project")
    benchmark.add_argument(
        "--request",
        type=Path,
        required=True,
        help="A pinned paired-model comparison request in JSON",
    )
    export = group.add_parser(
        "export", help="Export an immutable dataset version to a new ZIP file"
    )
    export.add_argument("project")
    export.add_argument("version_id")
    export.add_argument("--sha256", required=True, help="Dataset manifest SHA-256")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--format", default="yolo_detection")
    jobs = group.add_parser("job").add_subparsers(dest="verb", required=True)
    for name in ("status", "resume"):
        sub = jobs.add_parser(name)
        sub.add_argument("project")
        sub.add_argument("job_id")
    return cli


def _json_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise AutomationError("The input file must contain a JSON object.")
    return payload


def _execute(client: ReefVision, args: argparse.Namespace) -> dict[str, Any]:
    if args.group == "project":
        return (
            client.create_project(args.name)
            if args.verb == "create"
            else client.open_project(args.project)
        )
    project = args.project
    if args.group == "workflow":
        if args.verb == "plan":
            plan = client.plan_workflow(project, args.graph_id, args.sha256)
            if not plan.get("valid"):
                raise AutomationError(
                    "The selected workflow revision cannot run.", status=409, details=plan
                )
            return plan
        if args.verb == "status":
            return client.workflow(project, args.run_id)
        if args.verb == "resume":
            run = client.resume_workflow(project, args.run_id, args.node, args.reviewer, args.note)
        else:
            run = client.run_workflow(
                project,
                args.graph_id,
                args.sha256,
                inputs=_json_file(args.inputs) if args.inputs else None,
            )
        return client.wait(project, run["id"], workflow=True, seconds=args.timeout)
    if args.group == "infer":
        images = {}
        for spec in args.image:
            image, delimiter, digest = spec.partition("=")
            if not delimiter or image in images:
                raise AutomationError("Supply each original once as --image UUID=SHA256.")
            images[image] = digest
        job = client.infer(project, args.model, args.sha256, images, device=args.device)
        return client.wait(project, job["id"], seconds=args.timeout)
    if args.group == "benchmark":
        comparison = client.benchmark(project, _json_file(args.request))
        client.wait(project, comparison["id"], seconds=args.timeout)
        return {
            "job_id": comparison["id"],
            "report": client.benchmark_result(project, comparison["id"]),
        }
    if args.group == "export":
        if args.output.exists() or not args.output.parent.is_dir():
            raise AutomationError(
                "Choose a new ZIP filename in an existing output directory.", status=409
            )
        created = client.export(project, args.version_id, args.sha256, format=args.format)
        client.wait(project, created["job"]["id"], seconds=args.timeout)
        return {
            **client.download_export(project, created["export"]["id"], args.output),
            "job_id": created["job"]["id"],
            "dataset_version_id": args.version_id,
            "manifest_sha256": args.sha256,
        }
    if args.verb == "status":
        return client.job(project, args.job_id)
    job = client.resume_job(project, args.job_id)
    return client.wait(project, job["id"], seconds=args.timeout)


def run(argv: Sequence[str]) -> tuple[int, str]:
    cli = parser()
    if not argv:
        return 0, cli.format_help()
    try:
        captured = io.StringIO()
        try:
            with redirect_stdout(captured), redirect_stderr(captured):
                args = cli.parse_args(argv)
        except SystemExit as exc:
            if exc.code == 0:
                return 0, captured.getvalue()
            raise AutomationError(captured.getvalue().strip()) from exc
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise AutomationError("The wait time must be a positive number of seconds.")
        from reefvision.storage.automation_session import profile_service

        context = (
            profile_service(args.profile, args.timeout)
            if args.profile
            else nullcontext(ReefVision(args.api_url))
        )
        with context as client:
            info = client.system()
            if not str(info.get("application_version", "")).startswith("2."):
                raise AutomationError(
                    "Automation requires a local ReefVision 2.0 service.", status=409
                )
            result = _execute(client, args)
        review = (
            isinstance(result.get("run"), dict)
            and result["run"].get("status") == "waiting_for_review"
        )
        data = {
            "status": "review_required" if review else "ok",
            "application_version": info["application_version"],
            "result": result,
        }
        return (3 if review else 0), json.dumps(data, ensure_ascii=False, allow_nan=False) + "\n"
    except (AutomationError, OSError, ValueError) as exc:
        error = {
            "status": exc.status if isinstance(exc, AutomationError) else 400,
            "message": str(exc),
            "details": exc.details if isinstance(exc, AutomationError) else None,
        }
        return 2, json.dumps({"status": "error", "error": error}, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None, *, output: Path | None = None) -> int:
    status, message = run(sys.argv[1:] if argv is None else argv)
    if output is not None:
        with output.open("x", encoding="utf-8", newline="\n") as result:
            result.write(message)
    else:
        (sys.stderr if status not in {0, 3} else sys.stdout).write(message)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
