"""Verify the actual downloads and emit a record free of media or checkpoint bytes."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from hashlib import file_digest, sha256
from pathlib import Path
from typing import Any
from zipfile import ZipFile


def require(valid: bool, detail: str) -> None:
    if not valid:
        raise ValueError(detail)


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def verify_download(path: Path, download: dict) -> str:
    actual = digest(path)
    require(
        download["bytes"] == path.stat().st_size and download["sha256"] == actual,
        f"Independent download digest failed for {path.name}",
    )
    return actual


def verify_phase(
    phase: dict, detail: dict, browser: Path, fixture: dict, truth: dict, graph: dict
) -> dict:
    run = phase["run_id"]
    stored = detail["run"]
    train, inference = phase["training"], phase["inference"]
    registration = phase["registration_relation"]
    require(
        stored["id"] == run
        and stored["job_id"] == phase["parent_job_id"]
        and stored["workflow_graph_record_id"] == graph["id"]
        and stored["graph_sha256"] == graph["sha256"]
        and stored["status"] == phase["final_status"] == "succeeded",
        "Saved run terminal identity changed",
    )
    require(
        {node["node_type"] for node in detail["nodes"] if node["status"] == "succeeded"}
        >= {"pose_review_gate", "pose_active_learning_review_gate", "pose_training_export"},
        "Both actual human-review nodes and reviewed export must finish",
    )
    require(
        phase["after_temporal_review"] == "waiting_for_review"
        and phase.get("status_on_first_stop", phase.get("status_on_reopen")) == "waiting_for_review"
        and bool(phase["pre_acquisition_refusal"])
        and bool(phase["reviewed_artifact"])
        and phase["temporal_after"]["verified_breaks"]
        >= phase["temporal_before"]["automatic_breaks"],
        "The independently resumed temporal and acquisition gates did not appear and resolve",
    )
    train_id, validation_id = (item["id"] for item in fixture["datasets"])
    held = fixture["test_video"]
    require(
        train["training_dataset_id"] == train_id
        and train["validation_dataset_id"] == validation_id
        and train["device"] == phase["runtime_device"] == "cpu"
        and train["initialization"] == "random"
        and train["training_id"] == registration["training_run_id"]
        and train["registered_model_id"] == registration["model_id"]
        and train["checkpoint_sha256"] == registration["original_registered_bytes_sha256"]
        and inference["held_out_video"] == held["id"]
        and inference["held_out_sha256"] == held["sha256"]
        and inference["tracks"] > 0,
        "Frozen split, installed CPU job, original recording, or registration link changed",
    )

    train_archive = browser / f"{run}-training-results.zip"
    require(
        verify_download(train_archive, train["browser_download"])
        == train["verified_package_sha256"],
        "Training package did not match the verified runtime archive",
    )
    with ZipFile(train_archive) as archive:
        best = [name for name in archive.namelist() if name.endswith("/checkpoints/best.pt")]
        require(len(best) == 1, "The training download lacks exactly one selected checkpoint")
        with archive.open(best[0]) as stream:
            require(
                file_digest(stream, "sha256").hexdigest() == train["checkpoint_sha256"],
                "Training download contains a different checkpoint",
            )

    native = phase["native_pose_package"]
    pose_path = browser / f"{run}-poses.zip"
    require(
        verify_download(pose_path, native["browser_download"]) == native["sha256"]
        and native["lossy"] is False,
        "Reviewed native pose download did not match its runtime artifact",
    )
    with ZipFile(pose_path) as archive:
        manifest = json.loads(archive.read("reefvision-pose-training-manifest.json"))
        items = [json.loads(line) for line in archive.read("items.jsonl").splitlines()]
    review = phase["reviewed_reference"]
    require(
        Counter(row["status"] for row in phase["active_learning"]) == {"verified": 1, "skipped": 3}
        and manifest["project_id"] == fixture["project"]["id"]
        and manifest["dataset_id"] == native["dataset_id"]
        and manifest["source_round_id"] == phase["acquisition_shortcut"]["round_id"]
        and manifest["item_count"] == len(items) == 1
        and not manifest["pending_candidates_included"]
        and not manifest["skipped_candidates_included"],
        "Only the explicitly verified acquisition candidate belongs in the pose archive",
    )
    item = items[0]
    require(
        item["frame_index"] == review["frame"]
        and item["candidate_id"] == review["candidate_id"]
        and item["video_id"] == held["id"]
        and item["video_sha256"] == held["sha256"]
        and item["video_track_id"] in inference["track_ids"]
        and inference["job_id"] in item["source_job_ids"]
        and any(
            model["model_id"] == registration["model_id"]
            and model["checkpoint_sha256"] == train["checkpoint_sha256"]
            for model in item["source_models"]
        ),
        "Reviewed pose export lost recording, frame, candidate, track, job or model provenance",
    )
    expected = next(
        row["target_points"] for row in truth["frames"] if row["frame_index"] == review["frame"]
    )
    points = [
        {key: row[key] for key in ("landmark_id", "x", "y")}
        for row in item["canonical_pose"]["pose_observations"]
    ]
    require(
        points == expected == review["declared_source_pixels"],
        "Reviewed pose pixels changed from the frozen generated oracle",
    )
    view = phase["landmark_view"]
    require(
        [row["landmark_id"] for row in view] == [point["landmark_id"] for point in expected]
        and all(
            row["target_hits_canvas"]
            and row["inspector_collapsed_for_pointer"] != row["target_hit_canvas_before"]
            for row in view
        ),
        "Landmark edits require visible targets and an explicit inspector recovery",
    )
    for key, suffix in (("pose_csv", "pose.csv"), ("pose_audit", "pose-audit.json")):
        verify_download(browser / f"{run}-{suffix}", phase[key])

    return {
        "run_id": run,
        "parent_job_id": phase["parent_job_id"],
        "status": stored["status"],
        "human_gates": ["pose_review_gate", "pose_active_learning_review_gate"],
        "job_timing": phase["job_timing"],
        "registration": registration,
        "training": train,
        "inference": inference,
        "temporal_before": phase["temporal_before"],
        "temporal_reviewed_breaks": phase["temporal_after"]["verified_breaks"],
        "reviewed_frame": review["frame"],
        "landmark_view": view,
        "verified_candidates": 1,
        "skipped_candidates": 3,
        "pose_package": native,
        "pose_csv": phase["pose_csv"],
        "pose_audit": phase["pose_audit"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("fixture", "oracle", "browser", "output"):
        parser.add_argument(f"--{arg}", required=True, type=Path)
    for arg in ("source", "surface", "version", "schema"):
        parser.add_argument(f"--{arg}", required=True)
    args = parser.parse_args()
    fixture = read(args.fixture)
    oracle = read(args.oracle)["frozen_evaluation"]
    baseline = read(args.browser / "pose-predecessor-proof.json")
    replay = read(args.browser / "review-and-replay.json")
    require(
        re.fullmatch(r"[a-f0-9]{40}", args.source) is not None
        and fixture["source_commit"]
        == baseline["source_commit"]
        == replay["source_commit"]
        == args.source
        and baseline["surface"] == replay["surface"] == args.surface
        and baseline["version"] == replay["version"] == args.version
        and baseline["schema"] == replay["schema"] == args.schema,
        "The intended exact runtime, schema or browser surface changed",
    )
    require(
        fixture["project"]["id"] == baseline["project_id"]
        and baseline["graph"] == replay["graph"]
        and baseline["plan"]["executable"]
        and baseline["plan"]["valid"],
        "Guided saved graph identity or readiness changed",
    )
    chosen = baseline["guided_configuration"]
    require(
        chosen["template_id"] == "reefpose-native-reviewed-workflow"
        and not chosen["used_advanced_graph_for_composition"],
        "The journey must author the saved graph through the native guided template",
    )
    for port, dataset in zip(("train", "validation"), fixture["datasets"], strict=True):
        require(
            chosen[port]
            == {"dataset_id": dataset["id"], "manifest_sha256": dataset["manifest_sha256"]},
            f"Saved guided graph changed the frozen {port} dataset",
        )
    canonical = json.dumps(oracle["manifest"], sort_keys=True, separators=(",", ":")).encode()
    truth = oracle["manifest"]["sources"][0]
    require(
        sha256(canonical).hexdigest()
        == oracle["manifest_sha256"]
        == fixture["source_oracle_sha256"]
        == replay["held_out_truth_sha256"]
        and truth["split"] == "test"
        and truth["recording"] == fixture["test_video"]
        and len(truth["frames"]) == fixture["test_video"]["frame_count"],
        "Generated held-out oracle or identity changed",
    )
    for source in fixture["generated_sources"]:
        recording = source["recording"]
        require(
            digest(args.fixture.parent / recording["original_filename"]) == recording["sha256"],
            "A generated original recording changed after import and replay",
        )
    require(
        len(replay["phases"]) == 2
        and len(baseline["runs"]) == 1
        and replay["phases"][0]["run_id"] == baseline["runs"][0]["id"],
        "Two actual saved runs are required",
    )
    phases = [
        verify_phase(
            phase,
            read(args.browser / f"{phase['run_id']}-after-active-learning.json"),
            args.browser,
            fixture,
            truth,
            replay["graph"],
        )
        for phase in replay["phases"]
    ]
    for key in ("run_id", "parent_job_id"):
        require(phases[0][key] != phases[1][key], f"Replay did not create a distinct {key}")
    require(
        phases[0]["training"]["training_id"] != phases[1]["training"]["training_id"]
        and phases[0]["inference"]["job_id"] != phases[1]["inference"]["job_id"],
        "Replay must run its own training and inference jobs",
    )
    first, second = [phase["registration"] for phase in phases]
    same_bytes = (
        first["original_registered_bytes_sha256"] == second["original_registered_bytes_sha256"]
    )
    require(
        same_bytes
        == (first["model_id"] == second["model_id"])
        == replay["registration_comparison"]["reused_identical_bytes"],
        "Replay registration identity must follow actual checkpoint bytes",
    )
    args.output.write_text(
        json.dumps(
            {
                "source_commit": args.source,
                "surface": args.surface,
                "application_version": args.version,
                "schema_revision": args.schema,
                "generated_fixture_only": True,
                "project_id": fixture["project"]["id"],
                "graph": baseline["graph"],
                "fixture_sources": fixture["generated_sources"],
                "training_datasets": fixture["datasets"],
                "held_out_oracle_sha256": oracle["manifest_sha256"],
                "registration_comparison": replay["registration_comparison"],
                "runs": phases,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
