"""Monitoring evidence and local decision history survive Project Exchange."""

import json
from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import import_one
from reefvision.tests.test_monitoring import _alerts, _assess, _import, _root, _rule, _sample
from reefvision.tests.test_scientific_project_exchange import (
    MANIFEST,
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)


def test_monitoring_evidence_rebinds_twice_and_old_observations_stay_traceable(
    client: TestClient, test_settings: Settings
) -> None:
    project = _root(client, "Generated exchange monitoring")
    source_id = project.split("/")[-1]
    image = import_one(client, source_id)["successful"][0]["image_id"]
    (sample,) = _import(
        client, project, {**_sample(0, 71.6, "degF"), "subject": {"image_id": image}}
    )
    rule = _rule(client, project, label=image)
    first = _assess(client, project, rule)
    alert = next(row for row in _alerts(client, project, first) if row["kind"] == "upper_limit")
    review = client.post(
        project + "/monitoring/alerts/" + alert["id"] + "/reviews",
        json={"expected_revision": 0, "decision": "confirmed", "reason": image},
    )
    assert review.status_code == 201, review.text
    review = review.json()
    _import(client, project, _sample(1))
    latest = _assess(client, project, rule)
    old_project = source_id
    old_sample, old_rule, old_first, old_latest, old_alert = (
        sample["id"],
        rule["id"],
        first["id"],
        latest["id"],
        alert["id"],
    )
    original = export_archive(client, test_settings, source_id)
    archive = original
    for _ in range(2):
        imported = import_archive(client, archive)
        assert imported.status_code == 201, imported.text
        body = imported.json()
        current = body["project_id"]
        mapping = body["package"]["options_json"]["id_map"]
        assert current != old_project and current != source_id
        root = f"/api/v1/projects/{current}"
        restored_rule = client.get(root + "/monitoring/rules/" + mapping[old_rule]).json()
        assert restored_rule["label"] == image
        assert restored_rule["rule_sha256"] == rule["rule_sha256"]
        historic = client.get(root + "/monitoring/assessments/" + mapping[old_first]).json()
        restored = client.get(root + "/monitoring/assessments/" + mapping[old_latest]).json()
        assert historic["source_status"] == "stale"
        assert restored["source_status"] == "current"
        assert historic["result"]["estimate"] == first["result"]["estimate"]
        assert restored["result"]["estimate"] == latest["result"]["estimate"]
        assert _assess(client, root, restored_rule)["id"] == restored["id"]
        bound = historic["result"]["source_refs"][0]
        assert bound["id"] == mapping[old_sample]
        assert bound["sha256"] != sample["content_sha256"]
        assert bound["original_value"] == 71.6
        assert bound["original_unit"] == "degF"
        assert bound["normalized_unit"] == "degC"
        reviewed = client.get(root + "/monitoring/alerts/" + mapping[old_alert]).json()
        assert reviewed["status"] == "confirmed"
        assert reviewed["source_status"] == "stale"
        assert reviewed["proposal"]["source_ids"] == [bound["id"]]
        assert reviewed["finding_key"] == "upper_limit/" + bound["id"]
        for field in ("reviewer", "decision", "reason", "revision", "reviewed_at"):
            assert reviewed["latest_review"][field] == review[field]
        archive = export_archive(client, test_settings, current)
        old_project = current
        old_sample, old_rule, old_first, old_latest, old_alert = (
            bound["id"],
            restored_rule["id"],
            historic["id"],
            restored["id"],
            reviewed["id"],
        )
    assert client.get(project + "/monitoring/rules/" + rule["id"]).json() == rule

    def tamper(_manifest, sections):
        proposal = sections["monitoring_alerts"][0]
        proposal["proposal_json"]["detail"] = "Invented alert conclusion"
        proposal["proposal_sha256"] = canonical_json_sha256(proposal["proposal_json"])

    before = database_counts(client)
    rejected = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("changed.zip", rewrite(original, tamper), "application/zip")},
    )
    assert rejected.status_code == 200, rejected.text
    assert not rejected.json()["compatible"]
    assert database_counts(client) == before

    with ZipFile(BytesIO(original)) as package:
        descriptor = json.loads(package.read(MANIFEST))
    assert descriptor["format_version"] == "1.7.1"
