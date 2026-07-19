"""Schemas for ReefVision training, validation, and tuning reports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


ReportFontFamily = Literal[
    "system",
    "sans-serif",
    "serif",
    "monospace",
    "Arial",
    "Aptos",
    "Calibri",
    "Georgia",
    "Helvetica",
    "Times New Roman",
]


class TrainingReportCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    subtitle: str | None = Field(default=None, max_length=500)
    font_family: ReportFontFamily = "system"
    base_font_size_pt: float = Field(default=10.5, ge=7, le=24)
    heading_font_size_pt: float = Field(default=18, ge=10, le=48)
    table_font_size_pt: float = Field(default=9, ge=6, le=20)
    figure_label_font_size_pt: float = Field(default=9, ge=6, le=20)
    include_training_history: bool = True
    include_per_class_metrics: bool = True
    include_confusion_matrix: bool = True
    include_ultralytics_plots: bool = True
    include_tuning_analysis: bool = True
    include_provenance: bool = True

    @field_validator("title", "subtitle")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class TrainingReportResponse(BaseModel):
    report_id: str
    training_run_id: str
    title: str
    created_at: datetime
    font_family: str
    html_path: str
    json_path: str
    download_url: str
    included_sections: list[str]
    warnings: list[str]
