"""Annotation interoperability import schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnnotationImportIssue(BaseModel):
    """One non-fatal problem found while importing external annotations."""

    source_file: str | None = None
    image_reference: str | None = None
    annotation_id: str | None = None
    detail: str


class AnnotationImportResponse(BaseModel):
    """Structured report for a CoralNet-Toolbox annotation import."""

    project_id: str
    format: str = "coralnet_toolbox"
    files_processed: int = Field(ge=0)
    annotation_files: int = Field(ge=0)
    class_mapping_files: int = Field(ge=0)
    dataset_yaml_files: int = Field(ge=0)
    classes_matched: int = Field(ge=0)
    classes_created: int = Field(ge=0)
    boxes_imported: int = Field(ge=0)
    masks_imported: int = Field(ge=0)
    duplicate_annotations: int = Field(ge=0)
    unmatched_images: int = Field(ge=0)
    unknown_classes: int = Field(ge=0)
    skipped_annotations: int = Field(ge=0)
    issues: list[AnnotationImportIssue] = Field(default_factory=list)
