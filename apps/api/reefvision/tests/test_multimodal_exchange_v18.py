"""The portable format follows project contents and protects earlier scientific history."""

import json
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.tests.test_bioacoustics_v18 import recording
from reefvision.tests.test_image_adjustments_v18 import save_recipe, source_fixture
from reefvision.tests.test_images import import_one
from reefvision.tests.test_monitoring import _rule
from reefvision.tests.test_multispectral import spectral_fixture
from reefvision.tests.test_reviewer_lab_v15 import role_fixture, successful
from reefvision.tests.test_scientific_project_exchange import (
    MANIFEST,
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)
from reefvision.tests.test_taxonomy import organism, proposal_body, source


def test_new_taxonomy_history_selects_a_new_format_without_losing_monitoring(
    client: TestClient, test_settings: Settings
) -> None:
    project, _, roles = role_fixture(client)
    root = f"/api/v1/projects/{project}"
    rule = _rule(client, root)
    before = export_archive(client, test_settings, project)
    with ZipFile(BytesIO(before)) as package:
        assert json.loads(package.read(MANIFEST))["format_version"] == "1.7.1"

    proposal = successful(
        client.post(
            root + "/taxonomy/proposals",
            json=proposal_body(organism(client, root, 1), source(client, project, 1)),
            headers=roles["Reviewer A"][1],
        ),
        201,
    )
    archive = export_archive(client, test_settings, project)
    with ZipFile(BytesIO(archive)) as package:
        manifest = json.loads(package.read(MANIFEST))
        assert manifest["format_version"] == "1.8"
        assert manifest["sections"]["taxonomy_proposals"]["count"] == 1
        assert manifest["sections"]["monitoring_rules"]["count"] == 1

    altered = rewrite(archive, lambda m, _rows: m.update(format_version="1.7.1"))
    counts = database_counts(client)
    inspected = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("wrong-version.zip", altered, "application/zip")},
    )
    assert inspected.status_code == 200, inspected.text
    assert not inspected.json()["compatible"]
    assert import_archive(client, altered).status_code != 201
    assert database_counts(client) == counts

    imported = import_archive(client, archive)
    assert imported.status_code == 201, imported.text
    destination = f"/api/v1/projects/{imported.json()['project_id']}"
    mapping = imported.json()["package"]["options_json"]["id_map"]
    restored = successful(client.get(destination + "/taxonomy/proposals"))["items"]
    assert len(restored) == 1 and restored[0]["id"] == mapping[proposal["id"]]
    assert restored[0]["proposal_sha256"] == proposal["proposal_sha256"]
    assert restored[0]["proposal"] == proposal["proposal"]
    assert (
        successful(client.get(f"{destination}/monitoring/rules/{mapping[rule['id']]}"))[
            "rule_sha256"
        ]
        == rule["rule_sha256"]
    )


def test_one_research_project_restores_its_four_modalities_and_monitoring(
    client: TestClient, test_settings: Settings
) -> None:
    project, _, roles = role_fixture(client)
    root = f"/api/v1/projects/{project}"
    rule = _rule(client, root)
    taxon = successful(
        client.post(
            root + "/taxonomy/proposals",
            json=proposal_body(organism(client, root, 1), source(client, project, 1)),
            headers=roles["Reviewer A"][1],
        ),
        201,
    )
    rgb = source_fixture()
    image = import_one(client, project, content=rgb, filename="asymmetric.png")["successful"][0][
        "image_id"
    ]
    adjustment = save_recipe(client, image, rgb)
    sound, wav = recording(client, root + "/bioacoustics/assets")
    spectral, config, files = spectral_fixture(client, project)
    acq = successful(client.post(spectral + "/acquisitions", json=config), 201)
    index = successful(
        client.post(
            spectral + "/acquisitions/" + acq["id"] + "/indices",
            json={"positive": 1, "negative": 0, "acquisition_sha256": acq["content_sha256"]},
        ),
        201,
    )
    raw = export_archive(client, test_settings, project)
    with ZipFile(BytesIO(raw)) as archive:
        manifest = json.loads(archive.read(MANIFEST))
        assert manifest["format_version"] == "1.8"
        for section in (
            "monitoring_rules",
            "taxonomy_proposals",
            "bioacoustic_assets",
            "image_adjustment_recipes",
            "multispectral_indices",
        ):
            assert manifest["sections"][section]["count"] == 1
    restored = successful(import_archive(client, raw), 201)
    local = restored["package"]["options_json"]["id_map"]
    copied = "/api/v1/projects/" + restored["project_id"]
    assert (
        successful(client.get(copied + "/taxonomy/proposals"))["items"][0]["proposal"]
        == taxon["proposal"]
    )
    assert (
        successful(client.get(copied + "/monitoring/rules/" + local[rule["id"]]))["rule_sha256"]
        == rule["rule_sha256"]
    )
    assert (
        client.get(copied + "/bioacoustics/assets/" + local[sound["id"]] + "/content").content
        == wav
    )
    img = "/api/v1/images/" + local[image]
    assert client.get(img + "/content").content == rgb
    pixels = client.get(img + "/adjustments/" + local[adjustment["id"]] + "/rendition")
    assert (
        pixels.status_code == 200
        and sha256(pixels.content).hexdigest() == adjustment["receipt"]["rendition_sha256"]
    )
    saved = successful(
        client.get(copied + "/multispectral/indices/" + local[index["id"]] + "/export")
    )
    assert (
        saved["snapshot"] == index["snapshot"]
        and saved["content_sha256"] == index["content_sha256"]
    )
    for band, original in zip(config["bands"], files, strict=True):
        assert (
            client.get("/api/v1/images/" + local[band["image_id"]] + "/content").content == original
        )
