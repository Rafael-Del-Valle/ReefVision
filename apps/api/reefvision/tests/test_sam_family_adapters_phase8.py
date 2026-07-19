from __future__ import annotations

from pathlib import Path

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.ml.sam_adapters import infer_sam2_config
from reefvision.ml.sam_runtime_patch import apply_sam_runtime_patch
from reefvision.services import provider_capabilities


def test_sam2_config_is_inferred_from_standard_checkpoint_names() -> None:
    assert infer_sam2_config(Path("sam2.1_hiera_tiny.pt")) == ("configs/sam2.1/sam2.1_hiera_t.yaml")
    assert infer_sam2_config(Path("sam2_hiera_small.pth")) == ("configs/sam2/sam2_hiera_s.yaml")
    assert infer_sam2_config(Path("sam2.1_hiera_base_plus.pt")) == (
        "configs/sam2.1/sam2.1_hiera_b+.yaml"
    )
    assert infer_sam2_config(Path("sam2_hiera_large.pth")) == ("configs/sam2/sam2_hiera_l.yaml")


def test_sam2_config_rejects_ambiguous_checkpoint_name() -> None:
    with pytest.raises(ValidationError, match="Could not infer"):
        infer_sam2_config(Path("checkpoint.pth"))


def test_runtime_patch_registers_sam_family_capabilities() -> None:
    apply_sam_runtime_patch()
    provider_ids = {item.provider_id for item in provider_capabilities._PROVIDER_SPECS}
    assert "segment_anything" in provider_ids
    assert "mobilesam" in provider_ids
    assert "efficientvit_sam" in provider_ids
    assert "sam2" in provider_ids
