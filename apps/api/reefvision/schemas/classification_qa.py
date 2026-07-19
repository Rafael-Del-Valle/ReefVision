"""Classification crop quality assurance and augmentation schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ClassificationCropQARequest(BaseModel):
    crop_ids: list[str] = Field(default_factory=list, max_length=500_000)
    minimum_width_px: int = Field(default=32, ge=1, le=100_000)
    minimum_height_px: int = Field(default=32, ge=1, le=100_000)
    minimum_area_px: int = Field(default=1024, ge=1, le=10_000_000_000)
    maximum_aspect_ratio: float = Field(default=6.0, ge=1.0, le=1000.0)
    minimum_brightness: float = Field(default=8.0, ge=0, le=255)
    maximum_brightness: float = Field(default=247.0, ge=0, le=255)
    minimum_contrast_std: float = Field(default=4.0, ge=0, le=255)
    minimum_sharpness: float = Field(default=12.0, ge=0, le=1_000_000)
    maximum_dark_fraction: float = Field(default=0.85, ge=0, le=1)
    maximum_bright_fraction: float = Field(default=0.85, ge=0, le=1)
    duplicate_policy: Literal["error", "warning", "ignore"] = "warning"
    persist_report: bool = True

    @model_validator(mode="after")
    def brightness_order(self) -> ClassificationCropQARequest:
        if self.maximum_brightness <= self.minimum_brightness:
            raise ValueError("maximum_brightness must exceed minimum_brightness")
        return self


class ClassificationCropQAIssue(BaseModel):
    crop_id: str
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    measured_value: float | int | str | None = None
    threshold: float | int | str | None = None


class ClassificationCropQAMetrics(BaseModel):
    crop_id: str
    label_class_id: str
    managed_path: str
    exists: bool
    width_px: int | None
    height_px: int | None
    area_px: int | None
    aspect_ratio: float | None
    mean_brightness: float | None
    contrast_std: float | None
    sharpness: float | None
    dark_fraction: float | None
    bright_fraction: float | None
    sha256: str


class ClassificationCropQAResponse(BaseModel):
    project_id: str
    checked_at: str
    crop_count: int
    valid_crop_count: int
    error_count: int
    warning_count: int
    duplicate_group_count: int
    per_class_counts: dict[str, int]
    input_checksum: str
    report_checksum: str
    artifact_id: str | None
    metrics: list[ClassificationCropQAMetrics]
    issues: list[ClassificationCropQAIssue]
    warnings: list[str]


class ClassificationAugmentationConfig(BaseModel):
    horizontal_flip_probability: float = Field(default=0.5, ge=0, le=1)
    vertical_flip_probability: float = Field(default=0.0, ge=0, le=1)
    rotation_degrees: float = Field(default=15.0, ge=0, le=180)
    translate_fraction: float = Field(default=0.1, ge=0, le=0.9)
    scale_min: float = Field(default=0.85, gt=0, le=10)
    scale_max: float = Field(default=1.15, gt=0, le=10)
    brightness_jitter: float = Field(default=0.15, ge=0, le=1)
    contrast_jitter: float = Field(default=0.15, ge=0, le=1)
    saturation_jitter: float = Field(default=0.1, ge=0, le=1)
    hue_jitter: float = Field(default=0.02, ge=0, le=0.5)
    gaussian_blur_probability: float = Field(default=0.05, ge=0, le=1)
    gaussian_noise_probability: float = Field(default=0.05, ge=0, le=1)
    random_erasing_probability: float = Field(default=0.05, ge=0, le=1)
    mixup_probability: float = Field(default=0.0, ge=0, le=1)
    cutmix_probability: float = Field(default=0.0, ge=0, le=1)
    preserve_aspect_ratio: bool = True
    normalize_imagenet: bool = True
    random_seed: int = Field(default=42, ge=0, le=2_147_483_647)

    @model_validator(mode="after")
    def scale_order(self) -> ClassificationAugmentationConfig:
        if self.scale_max < self.scale_min:
            raise ValueError("scale_max must be greater than or equal to scale_min")
        return self


class ClassificationAugmentationValidationRequest(BaseModel):
    name: str = Field(default="Classifier augmentation preset", min_length=1, max_length=200)
    task: Literal["species", "state", "six_class", "custom"] = "custom"
    config: ClassificationAugmentationConfig
    save_as_artifact: bool = True


class ClassificationAugmentationValidationResponse(BaseModel):
    project_id: str
    name: str
    task: str
    valid: bool
    normalized_config: ClassificationAugmentationConfig
    config_checksum: str
    warnings: list[str]
    blockers: list[str]
    artifact_id: str | None
