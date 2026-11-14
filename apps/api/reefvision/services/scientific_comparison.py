"""Project-scoped scientific comparisons of already frozen ReefPose validation results."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from math import isclose
from statistics import fmean
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.db.models import Job, ModelRegistration
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.domain.reefpose_agreement import (
    cluster_interval,
    icc_absolute,
    measurement_agreement,
)
from reefvision.jobs.reefpose_validation import completed_report
from reefvision.schemas.scientific_comparison import (
    AgreementStatistics,
    ComparisonRecord,
    ComparisonRequest,
    ComparisonSnapshot,
    ExcludedValue,
    ModelAgreement,
    PairedModelDifference,
    PairedValue,
)
from reefvision.services.reefpose_validation import ReferenceService
from reefvision.storage.datasets import canonical_json_sha256

JOB_TYPE = "scientific_comparison"


def _group_interval(
    values: list[tuple[str, float]], options: ComparisonRequest
) -> tuple[float, float] | None:
    if not options.independent_groups:
        return None
    grouped: dict[str, list[float]] = defaultdict(list)
    for key, value in values:
        grouped[key].append(value)
    interval = cluster_interval(grouped, fmean, options.bootstrap_seed)
    return cast(tuple[float, float], tuple(interval)) if interval is not None else None


def agreement_statistics(
    rows: list[PairedValue], options: ComparisonRequest
) -> AgreementStatistics:
    if not rows:
        raise ValidationError("No comparable observations remain for this model and metric")
    n_groups = len({row.group_id for row in rows})
    independent = (
        options.independent_groups
        and n_groups == len(rows)
        and len(rows) >= 3
        and (
            options.metric != "event_count"
            or len({round((row.end_s or 0) - (row.start_s or 0), 9) for row in rows}) == 1
        )
    )
    values = [(row.reference, row.estimate) for row in rows]
    measurement = measurement_agreement(
        values, independent=independent and options.homoscedastic_normal_differences
    )
    percent = [
        (row.estimate - row.reference) / abs(row.reference) * 100
        for row in rows
        if row.reference != 0
    ]
    differences = [(row.group_id, row.estimate - row.reference) for row in rows]
    return AgreementStatistics(
        sample_count=len(rows),
        independent_groups=n_groups,
        zero_reference_count=len(rows) - len(percent),
        bias=measurement["bias"],
        mean_absolute_error=measurement["mae"],
        mean_absolute_percentage_error=fmean(map(abs, percent)) if percent else None,
        mean_signed_percentage_error=fmean(percent) if percent else None,
        limits_of_agreement=measurement["limits_of_agreement"],
        icc=icc_absolute([list(pair) for pair in values], consistency=options.icc == "C,1")
        if independent and options.icc
        else None,
        bias_ci95=_group_interval(differences, options),
        mae_ci95=_group_interval([(group, abs(value)) for group, value in differences], options),
    )


def _model_sources(
    session: Session, project_id: str, report: dict[str, Any]
) -> tuple[str, str, str]:
    model_ids = {source.get("model_id") for source in report["prediction_sources"]}
    if len(model_ids) != 1 or None in model_ids:
        raise ValidationError(
            "A comparison input must use one registered model across all recordings"
        )
    model_id = model_ids.pop()
    model = session.get(ModelRegistration, model_id)
    pinned = report["models"].get(model_id, {})
    if (
        model is None
        or model.project_id != project_id
        or model.sha256 != pinned.get("checkpoint_sha256")
    ):
        raise ValidationError("The source report is missing its matching registered checkpoint")
    return model.id, model.sha256, str(pinned.get("name") or model.display_name)


def scored_pairs(
    report: dict[str, Any], frozen: dict[str, Any], options: ComparisonRequest, source_id: str
) -> tuple[dict[tuple[str, str, float], PairedValue], list[ExcludedValue]]:
    expected = {row["video_id"]: row for row in frozen["recordings"] if row["split"] == "test"}
    recordings = report["recordings"]
    video_ids = [row["video_id"] for row in recordings]
    if sorted(video_ids) != sorted(expected):
        raise ValidationError(
            "Comparison report recordings must match the held-out reference split"
        )
    pairs: dict[tuple[str, str, float], PairedValue] = {}
    exclusions: list[ExcludedValue] = []
    for scored in sorted(recordings, key=lambda row: row["video_id"]):
        video_id = scored["video_id"]
        recording = expected[video_id]
        group = recording["group_id"]
        rater = next(
            (row for row in recording["annotations"] if row["rater_id"] == report["rater_id"]), None
        )
        if rater is None or group != scored["group_id"]:
            raise ValidationError(
                "Comparison report does not match the frozen rater or recording groups"
            )
        if options.metric == "event_count":
            known = {
                (row["individual_id"], row["start_s"]): row
                for row in recording["event_windows"]
                if row["label"] == options.name
            }
            scored_windows = {
                (row["individual_id"], row["start_s"]): row
                for row in scored["events"]
                if row["label"] == options.name
                and row["individual_id"]
                in {individual["id"] for individual in recording["individuals"]}
            }
            if scored_windows.keys() - known.keys():
                raise ValidationError("Scored event windows do not match the frozen reference")
            for (individual, start), window in sorted(known.items()):
                event = scored_windows.get((individual, start))
                if event is None or "excluded" in event:
                    exclusions.append(
                        ExcludedValue(
                            video_id=video_id,
                            individual_id=individual,
                            source_job_id=source_id,
                            start_s=start,
                            reason=event["excluded"] if event else "missing_window_result",
                        )
                    )
                    continue
                end = window["end_s"]
                reference = sum(
                    row["state"] == "complete"
                    and row["quality"] == "scored"
                    and row["label"] == options.name
                    and row["individual_id"] == individual
                    and start <= row["start_s"] < end
                    and row["end_s"] <= end
                    for row in rater["events"]
                )
                counts = event["complete"]
                if event["end_s"] != end or reference != counts["tp"] + counts["fn"]:
                    raise ValidationError("Scored counts do not match the frozen event reference")
                pairs[(video_id, individual, start)] = PairedValue(
                    video_id=video_id,
                    group_id=group,
                    individual_id=individual,
                    start_s=start,
                    end_s=end,
                    reference=reference,
                    estimate=counts["tp"] + counts["fp"],
                )
        else:
            reference_rows = {
                (row["individual_id"], row["frame"]): row
                for row in rater["measurements"]
                if row["definition_id"] == options.name and row["unit"] == options.unit
            }
            predictions = {
                (row["individual_id"], frame): point
                for row in scored["measurements"]
                if row["definition_id"] == options.name and row["unit"] == options.unit
                for frame, point in zip(row["matched_frames"], row["points"], strict=True)
            }
            if predictions.keys() - reference_rows.keys():
                raise ValidationError("Scored sample frames do not match the frozen reference")
            for (individual, frame), sample in sorted(reference_rows.items()):
                point = predictions.get((individual, frame))
                if sample["state"] != "scored" or point is None:
                    exclusions.append(
                        ExcludedValue(
                            video_id=video_id,
                            individual_id=individual,
                            source_job_id=source_id,
                            frame=frame,
                            reason=(
                                "no_matched_prediction"
                                if sample["state"] == "scored"
                                else f"{sample['state']}_reference"
                            ),
                        )
                    )
                    continue
                reference = sample["value"]
                estimate = reference + point["difference"]
                if not isclose(
                    point["mean"], reference + point["difference"] / 2, rel_tol=1e-9, abs_tol=1e-9
                ):
                    raise ValidationError(
                        "Scored measurement values do not match the frozen reference"
                    )
                pairs[(video_id, individual, frame)] = PairedValue(
                    video_id=video_id,
                    group_id=group,
                    individual_id=individual,
                    frame=frame,
                    reference=reference,
                    estimate=estimate,
                )
    return pairs, exclusions


def paired_model_difference(
    models: list[ModelAgreement], options: ComparisonRequest
) -> PairedModelDifference | None:
    if len(models) != 2:
        return None

    def key(row: PairedValue) -> tuple[UUID, str, int | float]:
        coordinate = row.frame if row.frame is not None else row.start_s
        if coordinate is None:
            raise ValidationError("Paired held-out evidence requires a frame or window")
        return row.video_id, row.individual_id, coordinate

    first, second = models
    right_by_key = {key(row): row for row in second.pairs}
    if (
        len(right_by_key) != len(second.pairs)
        or {key(row) for row in first.pairs} != right_by_key.keys()
        or len(first.pairs) != len(right_by_key)
    ):
        raise ValidationError("Paired models require the same unique held-out evidence")
    paired = []
    for left in sorted(first.pairs, key=key):
        right = right_by_key[key(left)]
        if (left.group_id, left.reference, left.end_s) != (
            right.group_id,
            right.reference,
            right.end_s,
        ):
            raise ValidationError("Paired models disagree on their shared held-out reference")
        change = abs(right.estimate - right.reference) - abs(left.estimate - left.reference)
        paired.append((left.group_id, change))
    return PairedModelDifference(
        sample_count=len(paired),
        independent_groups=len({group for group, _ in paired}),
        absolute_error_change=fmean(value for _, value in paired),
        absolute_error_change_ci95=_group_interval(paired, options),
    )


def calculate_comparison(
    session: Session, project_id: str, options: ComparisonRequest
) -> ComparisonSnapshot:
    report_ids = [str(identifier) for identifier in options.source_job_ids]
    reports = [completed_report(session, project_id, identifier) for identifier in report_ids]
    first = reports[0]
    reference = ReferenceService(session).get(project_id, first["reference_id"])
    if reference.manifest_sha256 != first["reference_sha256"]:
        raise ValidationError("The scoring report no longer matches its frozen reference")
    matched_fields = (
        "reference_id",
        "reference_sha256",
        "rater_id",
        "selected_configuration",
        "tracker_protocol",
    )
    if any(
        row["split"] != "test" or any(row[key] != first[key] for key in matched_fields)
        for row in reports
    ):
        raise ValidationError(
            "Choose held-out reports with the same frozen reference, rater, and scoring protocol"
        )
    locked_protocols = [
        {item["video_id"]: item.get("upstream_protocol") for item in row["prediction_sources"]}
        for row in reports
    ]
    if any(protocol != locked_protocols[0] for protocol in locked_protocols[1:]):
        raise ValidationError("Model reports must use the same upstream inference protocol")
    if options.metric == "measurement" and any(
        row["id"] == options.name and row["kind"] in {"direction", "body_axis_orientation"}
        for row in first["selected_configuration"]["definitions"]
    ):
        raise ValidationError("Circular angles require circular agreement methods")
    models: list[ModelAgreement] = []
    sources = [_model_sources(session, project_id, row) for row in reports]
    if len({model[1] for model in sources}) != len(sources):
        raise ValidationError("Choose distinct registered checkpoints for paired model comparison")
    pair_maps = []
    exclusions = []
    for report_id, report in zip(report_ids, reports, strict=True):
        pairs, excluded = scored_pairs(report, reference.manifest, options, report_id)
        pair_maps.append(pairs)
        exclusions.extend(excluded)
    shared = sorted(set.intersection(*(set(pairs) for pairs in pair_maps)))
    if not shared:
        raise ValidationError("The selected model reports have no common comparable observations")
    for report_id, report, model, pairs in zip(
        report_ids, reports, sources, pair_maps, strict=True
    ):
        values = [pairs[key] for key in shared]
        for key in sorted(pairs.keys() - set(shared)):
            row = pairs[key]
            exclusions.append(
                ExcludedValue(
                    video_id=row.video_id,
                    individual_id=row.individual_id,
                    source_job_id=report_id,
                    frame=row.frame,
                    start_s=row.start_s,
                    reason="missing_pair_for_other_model",
                )
            )
        models.append(
            ModelAgreement(
                source_job_id=report_id,
                source_result_sha256=report["result_sha256"],
                model_id=model[0],
                checkpoint_sha256=model[1],
                model_name=model[2],
                pairs=values,
                statistics=agreement_statistics(values, options),
            )
        )
    pairing = paired_model_difference(models, options)
    return ComparisonSnapshot(
        data_kind=reference.data_kind,
        reference_id=reference.id,
        reference_sha256=reference.manifest_sha256,
        rater_id=first["rater_id"],
        configuration_sha256=canonical_json_sha256(first["selected_configuration"]),
        options=options,
        software_version=__version__,
        models=models,
        pairing=pairing,
        exclusions=exclusions,
        limitations=[
            "Agreement is relative to the chosen frozen human reference.",
            "Percent errors exclude zero reference values. Raw errors retain those observations.",
            "Intervals use a 95% percentile bootstrap over at least five investigator-attested "
            "recording groups. Resampling retains every pair within each selected group.",
            "Bland-Altman limits require one independent pair per group, equal count-window "
            "duration where applicable, and approximately normal differences with constant "
            "variance.",
            "ICC(A,1) is single-rating absolute agreement. ICC(C,1) is single-rating "
            "consistency and is invariant to a fixed method offset.",
            "Event counts apply to adjudicated or individually reviewed windows for known "
            "reference subjects. Unassigned model tracks are outside this count estimand.",
        ],
    )


def _result_sha(snapshot: ComparisonSnapshot) -> str:
    return canonical_json_sha256(snapshot.model_dump(mode="json"))


def create_comparison(
    session: Session, project_id: str, options: ComparisonRequest
) -> ComparisonRecord:
    snapshot = calculate_comparison(session, project_id, options)
    now = datetime.now(UTC)
    job = Job(
        project_id=project_id,
        job_type=JOB_TYPE,
        status="succeeded",
        started_at=now,
        completed_at=now,
        progress_current=1,
        progress_total=1,
        request_json=options.model_dump(mode="json"),
        result_json={
            "snapshot": snapshot.model_dump(mode="json"),
            "content_sha256": _result_sha(snapshot),
            "local_sources": [
                {"job_id": str(model.source_job_id), "result_sha256": model.source_result_sha256}
                for model in snapshot.models
            ],
            "source_id_map": {},
        },
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return read_comparison(session, project_id, job.id)


def decode_comparison(session: Session, job: Job) -> ComparisonRecord:
    result = ComparisonRecord.model_validate(
        {
            **(job.result_json or {}),
            "id": job.id,
            "project_id": job.project_id,
        }
    )
    if result.content_sha256 != _result_sha(result.snapshot):
        raise ValidationError("Saved comparison checksum does not match")
    for source in result.local_sources:
        try:
            current = completed_report(session, str(result.project_id), str(source.job_id))
        except (NotFoundError, ValidationError):
            result.stale = True
            break
        if current["result_sha256"] != source.result_sha256:
            result.stale = True
            break
    return result


def read_comparison(session: Session, project_id: str, identifier: str) -> ComparisonRecord:
    row = session.get(Job, identifier)
    if (
        row is None
        or row.project_id != project_id
        or row.job_type != JOB_TYPE
        or row.status != "succeeded"
    ):
        raise NotFoundError("Saved comparison was not found")
    return decode_comparison(session, row)


def list_comparisons(
    session: Session, project_id: str, limit: int, offset: int
) -> list[ComparisonRecord]:
    jobs = session.scalars(
        select(Job)
        .where(Job.project_id == project_id, Job.job_type == JOB_TYPE, Job.status == "succeeded")
        .order_by(Job.created_at.desc(), Job.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [decode_comparison(session, job) for job in jobs]
