from __future__ import annotations

from pathlib import Path

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.ml.semantic_segmentation import (
    PlannedNnUNetProvider,
    SemanticClassDefinition,
    SemanticDatasetContract,
    SemanticTrainingRequest,
    semantic_provider_for_name,
)


def _dataset(tmp_path: Path) -> SemanticDatasetContract:
    export_root = tmp_path / "semantic-export"
    images_root = export_root / "images"
    masks_root = export_root / "masks"
    images_root.mkdir(parents=True)
    masks_root.mkdir(parents=True)
    classes_file = export_root / "classes.json"
    classes_file.write_text("{}", encoding="utf-8")
    return SemanticDatasetContract(
        dataset_version_id="dataset-1",
        dataset_manifest_sha256="a" * 64,
        split_manifest_sha256="b" * 64,
        export_root=export_root,
        images_root=images_root,
        masks_root=masks_root,
        classes_file=classes_file,
        classes=(
            SemanticClassDefinition(
                class_index=0,
                pixel_value=1,
                class_name="soft coral",
            ),
        ),
        overlap_policy="higher class index overwrites lower class index",
    )


def test_semantic_dataset_contract_validates_indexed_png_layout(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path)
    dataset.validate()


def test_semantic_dataset_contract_rejects_background_as_foreground(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path)
    invalid = SemanticDatasetContract(
        **{
            **dataset.__dict__,
            "classes": (
                SemanticClassDefinition(
                    class_index=0,
                    pixel_value=0,
                    class_name="soft coral",
                ),
            ),
        }
    )
    with pytest.raises(ValidationError, match="between 1 and 255"):
        invalid.validate()


def test_planned_nnunet_provider_is_explicitly_capability_gated(
    tmp_path: Path,
) -> None:
    provider = semantic_provider_for_name("nnunet")
    assert isinstance(provider, PlannedNnUNetProvider)
    request = SemanticTrainingRequest(
        run_id="run-1",
        project_id="project-1",
        dataset=_dataset(tmp_path),
    )
    warnings, blockers = provider.preflight(request)
    assert warnings == []
    assert len(blockers) == 1
    assert "not installed" in blockers[0]
    with pytest.raises(ValidationError, match="not implemented"):
        provider.train(request)
