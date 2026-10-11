"""Executable optional advanced-provider adapters."""

from __future__ import annotations

import base64
import io
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.optional_transformers_runtime import (
    OPTIONAL_MODEL_SPECS,
    ensure_optional_model,
    optional_model_status,
    resolve_torch_device,
)
from reefvision.ml.providers import mask_to_box
from reefvision.repositories.images import ImageRepository
from reefvision.schemas.advanced_provider_execution import (
    AdvancedProviderExecutionRequest,
    AdvancedProviderExecutionResponse,
)
from reefvision.services.advanced_provider_proposals import (
    persist_grounding_dino_proposals,
    persist_sam2_proposal,
)
from reefvision.services.sam2_install import sam2_status, variant_repo
from reefvision.storage.projects import resolve_managed_project_path

SAM2_RUNTIME_LOG = logging.getLogger("reefvision.advanced.sam2")

PROVIDER_LAB_EXECUTION_IDS: frozenset[str] = frozenset(
    {
        "grounding_dino",
        "sam2",
        "smolvlm",
        "nnunet",
    }
)


def optional_provider_runtime_status(settings: Settings, provider_id: str) -> dict[str, Any]:
    if provider_id in OPTIONAL_MODEL_SPECS:
        return optional_model_status(settings, provider_id)
    if provider_id == "nnunet":
        command = shutil.which("nnUNetv2_predict")
        required_env = {
            key: os.environ.get(key)
            for key in ("nnUNet_raw", "nnUNet_preprocessed", "nnUNet_results")
        }
        missing_env = [key for key, value in required_env.items() if not value]
        return {
            "provider_id": provider_id,
            "ready": command is not None and not missing_env,
            "cached": True,
            "verified": command is not None,
            "path": command,
            "reason": (
                None
                if command is not None and not missing_env
                else (
                    "Install nnunetv2 and configure nnUNet_raw, "
                    "nnUNet_preprocessed, and nnUNet_results."
                )
            ),
            "missing_environment": missing_env,
        }
    raise ValidationError(
        f"No executable optional provider runtime is registered for {provider_id}"
    )


def _as_float(value: object, *, name: str, minimum: float = 0.0, maximum: float = 1.0) -> float:
    if not isinstance(value, (str, int, float)):
        raise ValidationError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be numeric") from exc
    if not minimum <= number <= maximum:
        raise ValidationError(f"{name} must be between {minimum} and {maximum}")
    return number


def _string_list(value: object, *, name: str) -> list[str]:
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        raise ValidationError(f"{name} must be a string or list of strings")
    items = [item for item in items if item]
    if not items:
        raise ValidationError(f"{name} cannot be empty")
    return items


def _image(
    session: Session, settings: Settings, project_id: str, image_id: object
) -> tuple[Path, Image.Image]:
    if not isinstance(image_id, str) or not image_id:
        raise ValidationError("Select an image for this provider action")
    record = ImageRepository(session).get_basic(image_id)
    if record is None or record.project_id != project_id:
        raise NotFoundError("Image not found in this project")
    path = resolve_managed_project_path(settings, record.managed_path)
    if not path.is_file():
        raise ValidationError("The managed image file is missing")
    with Image.open(path) as source:
        source.load()
        return path, source.convert("RGB")


def _mask_png_base64(mask: Any) -> str:
    import numpy as np

    data = np.asarray(mask, dtype=bool)
    image = Image.fromarray(data.astype("uint8") * 255, mode="L")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


class AdvancedProviderExecutionService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def execute(
        self,
        project_id: str,
        provider_id: str,
        request: AdvancedProviderExecutionRequest,
    ) -> AdvancedProviderExecutionResponse:
        if provider_id not in PROVIDER_LAB_EXECUTION_IDS:
            raise ValidationError("This provider does not execute through Advanced Provider Lab")

        if provider_id == "grounding_dino":
            return self._grounding_dino(project_id, request)
        if provider_id == "sam2":
            return self._sam2(project_id, request)
        if provider_id == "smolvlm":
            return self._smolvlm(project_id, request)
        if provider_id == "nnunet":
            return self._nnunet(request)
        raise ValidationError(f"Advanced provider execution is not implemented for {provider_id}")

    def _grounding_dino(
        self, project_id: str, request: AdvancedProviderExecutionRequest
    ) -> AdvancedProviderExecutionResponse:
        if request.task not in {"open_vocabulary_detect", "phrase_grounding"}:
            raise ValidationError(
                "Grounding DINO supports open-vocabulary detection and phrase grounding"
            )
        _, image = _image(
            self.session, self.settings, project_id, request.prompt_fields.get("image_id")
        )
        labels = _string_list(request.prompt_fields.get("text_prompts"), name="text_prompts")
        threshold = _as_float(request.prompt_fields.get("confidence", 0.35), name="confidence")
        text_threshold = _as_float(
            request.prompt_fields.get("text_threshold", 0.25), name="text_threshold"
        )
        model_path = ensure_optional_model(
            self.settings,
            "grounding_dino",
            allow_download=request.allow_model_download,
        )
        try:
            import torch
            from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
        except Exception as exc:
            raise ValidationError(f"Grounding DINO runtime is unavailable: {exc}") from exc
        device = resolve_torch_device(request.device)
        processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)  # type: ignore[no-untyped-call]
        model = AutoModelForZeroShotObjectDetection.from_pretrained(
            model_path, local_files_only=True
        ).to(device)
        model.eval()
        inputs = processor(images=image, text=[labels], return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model(**inputs)
        results = processor.post_process_grounded_object_detection(
            outputs,
            threshold=threshold,
            text_threshold=text_threshold,
            target_sizes=[(image.height, image.width)],
        )[0]
        text_labels = results.get("text_labels") or results.get("labels") or []
        detections = []
        for box, score, label in zip(
            results["boxes"], results["scores"], text_labels, strict=False
        ):
            coords = [float(value) for value in box.tolist()]
            detections.append(
                {
                    "label": str(label),
                    "confidence": float(score.item()),
                    "box": {
                        "x_min": coords[0],
                        "y_min": coords[1],
                        "x_max": coords[2],
                        "y_max": coords[3],
                    },
                }
            )
        spec = OPTIONAL_MODEL_SPECS["grounding_dino"]
        image_id = str(request.prompt_fields.get("image_id") or "")
        proposal_ids = persist_grounding_dino_proposals(
            self.session,
            self.settings,
            project_id=project_id,
            image_id=image_id,
            runtime_path=model_path,
            device=str(device),
            task=request.task,
            detections=detections,
            prompt_labels=labels,
            confidence_threshold=threshold,
            text_threshold=text_threshold,
        )
        persisted_detections = [
            {**detection, "proposal_id": proposal_id, "image_id": image_id}
            for detection, proposal_id in zip(detections, proposal_ids, strict=True)
        ]
        return AdvancedProviderExecutionResponse(
            provider_id="grounding_dino",
            task=request.task,
            model_id=spec.repo_id,
            model_revision=spec.revision,
            result={
                "image_id": image_id,
                "detections": persisted_detections,
                "prompt_labels": labels,
                "proposal_ids": proposal_ids,
                "proposal_count": len(proposal_ids),
                "review_status": "pending",
            },
            warnings=[
                "Grounding DINO detections were saved as pending prediction "
                "proposals; a researcher must review them before they become "
                "verified annotations."
            ],
        )

    def _sam2(
        self, project_id: str, request: AdvancedProviderExecutionRequest
    ) -> AdvancedProviderExecutionResponse:
        if request.task != "assist_segmentation":
            raise ValidationError("This SAM 2 adapter currently executes image assist segmentation")
        started = time.perf_counter()
        variant = str(request.prompt_fields.get("sam2_variant", "small"))
        SAM2_RUNTIME_LOG.info("SAM2 stage=start variant=%s device=%s", variant, request.device)
        _, image = _image(
            self.session, self.settings, project_id, request.prompt_fields.get("image_id")
        )
        SAM2_RUNTIME_LOG.info(
            "SAM2 stage=image_ready elapsed=%.2fs variant=%s",
            time.perf_counter() - started,
            variant,
        )
        variant_repo(variant)
        SAM2_RUNTIME_LOG.info(
            "SAM2 stage=status_start elapsed=%.2fs", time.perf_counter() - started
        )
        installed = sam2_status(self.settings, variant)
        SAM2_RUNTIME_LOG.info(
            "SAM2 stage=status_complete elapsed=%.2fs ready=%s",
            time.perf_counter() - started,
            installed["ready"],
        )
        if not installed["ready"]:
            raise ValidationError(str(installed["reason"]))
        model_path = Path(str(installed["path"]))
        try:
            SAM2_RUNTIME_LOG.info(
                "SAM2 stage=numpy_import_start elapsed=%.2fs",
                time.perf_counter() - started,
            )
            import numpy as np
            SAM2_RUNTIME_LOG.info(
                "SAM2 stage=numpy_import_complete elapsed=%.2fs",
                time.perf_counter() - started,
            )
            SAM2_RUNTIME_LOG.info(
                "SAM2 stage=torch_import_start elapsed=%.2fs",
                time.perf_counter() - started,
            )
            import torch
            SAM2_RUNTIME_LOG.info(
                "SAM2 stage=torch_import_complete elapsed=%.2fs",
                time.perf_counter() - started,
            )
            SAM2_RUNTIME_LOG.info(
                "SAM2 stage=transformers_import_start elapsed=%.2fs",
                time.perf_counter() - started,
            )
            from transformers import Sam2Model, Sam2Processor
            SAM2_RUNTIME_LOG.info(
                "SAM2 stage=transformers_import_complete elapsed=%.2fs",
                time.perf_counter() - started,
            )
        except Exception as exc:
            SAM2_RUNTIME_LOG.exception("SAM2 stage=runtime_import_failed")
            raise ValidationError(f"SAM 2 runtime is unavailable: {exc}") from exc
        SAM2_RUNTIME_LOG.info(
            "SAM2 stage=runtime_imported elapsed=%.2fs torch_threads=%d",
            time.perf_counter() - started,
            torch.get_num_threads(),
        )
        device = resolve_torch_device(request.device)
        processor = Sam2Processor.from_pretrained(model_path, local_files_only=True)
        SAM2_RUNTIME_LOG.info(
            "SAM2 stage=processor_loaded elapsed=%.2fs",
            time.perf_counter() - started,
        )
        model = Sam2Model.from_pretrained(model_path, local_files_only=True)
        SAM2_RUNTIME_LOG.info(
            "SAM2 stage=weights_loaded elapsed=%.2fs",
            time.perf_counter() - started,
        )
        model = model.to(device).eval()
        SAM2_RUNTIME_LOG.info(
            "SAM2 stage=model_ready elapsed=%.2fs device=%s",
            time.perf_counter() - started,
            device,
        )

        kwargs: dict[str, Any] = {"images": image, "return_tensors": "pt"}
        raw_box = request.prompt_fields.get("box")
        raw_points = request.prompt_fields.get("points")
        if raw_box is not None:
            if not isinstance(raw_box, list) or len(raw_box) != 4:
                raise ValidationError("SAM 2 box must be [x_min, y_min, x_max, y_max]")
            prompt_box = [float(value) for value in raw_box]
            if prompt_box[2] <= prompt_box[0] or prompt_box[3] <= prompt_box[1]:
                raise ValidationError("SAM 2 box must have positive width and height")
            kwargs["input_boxes"] = [[prompt_box]]
        elif raw_points is not None:
            if not isinstance(raw_points, list) or not raw_points:
                raise ValidationError("SAM 2 points must be a non-empty list")
            points = [[float(point[0]), float(point[1])] for point in raw_points]
            labels = request.prompt_fields.get("labels")
            if labels is None:
                labels = [1] * len(points)
            if not isinstance(labels, list) or len(labels) != len(points):
                raise ValidationError("SAM 2 labels must match the point count")
            kwargs["input_points"] = [[points]]
            kwargs["input_labels"] = [[[int(value) for value in labels]]]
        else:
            raise ValidationError("SAM 2 requires either a box or point prompts")

        inputs = processor(**kwargs).to(device)
        SAM2_RUNTIME_LOG.info(
            "SAM2 stage=inputs_ready elapsed=%.2fs pixels=%s",
            time.perf_counter() - started,
            tuple(inputs["pixel_values"].shape),
        )
        with torch.inference_mode():
            outputs = model(**inputs, multimask_output=False)
        SAM2_RUNTIME_LOG.info(
            "SAM2 stage=forward_complete elapsed=%.2fs",
            time.perf_counter() - started,
        )
        masks = processor.post_process_masks(outputs.pred_masks.cpu(), inputs["original_sizes"])[0]  # type: ignore[no-untyped-call]
        mask_tensor = masks[0, 0] if masks.ndim == 4 else masks[0]
        mask = np.asarray(mask_tensor, dtype=bool)
        mask_box = mask_to_box(mask)
        score = 0.0
        if getattr(outputs, "iou_scores", None) is not None:
            score = float(outputs.iou_scores.detach().cpu().reshape(-1)[0].item())
        image_id = str(request.prompt_fields.get("image_id") or "")
        mask_png_base64 = _mask_png_base64(mask)
        proposal_box = {
            "x_min": mask_box.x_min,
            "y_min": mask_box.y_min,
            "x_max": mask_box.x_max,
            "y_max": mask_box.y_max,
        }
        SAM2_RUNTIME_LOG.info(
            "SAM2 stage=mask_ready elapsed=%.2fs area=%d",
            time.perf_counter() - started,
            int(mask.sum()),
        )
        proposal_id = persist_sam2_proposal(
            self.session,
            self.settings,
            project_id=project_id,
            image_id=image_id,
            runtime_path=model_path,
            device=str(device),
            mask_png_base64=mask_png_base64,
            score=score,
            box=proposal_box,
            prompt_fields=dict(request.prompt_fields),
            source_repo_id=variant_repo(variant),
            source_revision=str(installed["revision"]),
            source_checksum=str(installed["weight_sha256"]),
            source_variant=variant,
        )
        SAM2_RUNTIME_LOG.info(
            "SAM2 stage=proposal_persisted elapsed=%.2fs",
            time.perf_counter() - started,
        )
        return AdvancedProviderExecutionResponse(
            provider_id="sam2",
            task=request.task,
            model_id=variant_repo(variant),
            model_revision=str(installed["revision"]),
            result={
                "image_id": image_id,
                "proposal_id": proposal_id,
                "proposal_ids": [proposal_id],
                "proposal_count": 1,
                "review_status": "pending",
                "mask_png_base64": mask_png_base64,
                "score": score,
                "area_pixels": int(mask.sum()),
                "box": proposal_box,
            },
            warnings=[
                "SAM 2 output was saved as a pending raster-mask proposal; "
                "a researcher must review it before it becomes a verified "
                "mask annotation."
            ],
        )

    def _smolvlm(
        self, project_id: str, request: AdvancedProviderExecutionRequest
    ) -> AdvancedProviderExecutionResponse:
        if request.task not in {"caption", "visual_question"}:
            raise ValidationError("SmolVLM supports caption and visual-question tasks")
        _, image = _image(
            self.session, self.settings, project_id, request.prompt_fields.get("image_id")
        )
        prompt = str(
            request.prompt_fields.get("prompt")
            or (
                "Describe the scientifically relevant visible content in this image."
                if request.task == "caption"
                else "Describe this image."
            )
        ).strip()
        if not prompt:
            raise ValidationError("VLM prompt cannot be blank")
        max_new_tokens = int(request.prompt_fields.get("max_new_tokens", 128))
        max_new_tokens = max(8, min(512, max_new_tokens))
        model_path = ensure_optional_model(
            self.settings,
            "smolvlm",
            allow_download=request.allow_model_download,
        )
        try:
            import torch
            from transformers import AutoModelForVision2Seq, AutoProcessor
        except Exception as exc:
            raise ValidationError(f"SmolVLM runtime is unavailable: {exc}") from exc
        device = resolve_torch_device(request.device)
        processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)  # type: ignore[no-untyped-call]
        model = AutoModelForVision2Seq.from_pretrained(model_path, local_files_only=True).to(device)  # type: ignore[no-untyped-call]
        model.eval()
        messages = [
            {
                "role": "user",
                "content": [{"type": "image"}, {"type": "text", "text": prompt}],
            }
        ]
        chat_prompt = processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = processor(text=chat_prompt, images=[image], return_tensors="pt").to(device)
        with torch.no_grad():
            generated = model.generate(**inputs, max_new_tokens=max_new_tokens)
        prefix = inputs["input_ids"].shape[-1]
        text = processor.decode(generated[0][prefix:], skip_special_tokens=True).strip()
        spec = OPTIONAL_MODEL_SPECS["smolvlm"]
        return AdvancedProviderExecutionResponse(
            provider_id="smolvlm",
            task=request.task,
            model_id=spec.repo_id,
            model_revision=spec.revision,
            result={"text": text, "prompt": prompt},
            warnings=[
                "VLM text is advisory and must not automatically alter labels, "
                "measurements, or scientific conclusions."
            ],
        )

    def _nnunet(
        self, request: AdvancedProviderExecutionRequest
    ) -> AdvancedProviderExecutionResponse:
        if request.task != "semantic_segment":
            raise ValidationError("nnU-Net adapter supports semantic_segment")
        status = optional_provider_runtime_status(self.settings, "nnunet")
        if not status["ready"]:
            raise ValidationError(str(status["reason"]))
        command = str(status["path"])
        fields = request.prompt_fields
        input_folder = Path(str(fields.get("input_folder") or "")).expanduser().resolve()
        output_folder = Path(str(fields.get("output_folder") or "")).expanduser().resolve()
        dataset = str(fields.get("dataset") or "").strip()
        configuration = str(fields.get("configuration") or "3d_fullres").strip()
        if not input_folder.is_dir():
            raise ValidationError("nnU-Net input_folder must be an existing directory")
        if not dataset:
            raise ValidationError("nnU-Net dataset identifier is required")
        output_folder.mkdir(parents=True, exist_ok=True)
        args = [
            command,
            "-i",
            str(input_folder),
            "-o",
            str(output_folder),
            "-d",
            dataset,
            "-c",
            configuration,
        ]
        folds = fields.get("folds")
        if isinstance(folds, list) and folds:
            args.extend(["-f", *[str(value) for value in folds]])
        device = request.device.strip().lower()
        if device in {"cpu", "cuda"}:
            args.extend(["-device", device])
        timeout_seconds = int(fields.get("timeout_seconds", 7200))
        timeout_seconds = max(60, min(86_400, timeout_seconds))
        try:
            completed = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValidationError("nnU-Net prediction exceeded the configured timeout") from exc
        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "")[-4000:]
            raise ValidationError(f"nnU-Net prediction failed: {tail}")
        return AdvancedProviderExecutionResponse(
            provider_id="nnunet",
            task=request.task,
            result={
                "output_folder": str(output_folder),
                "command": args,
                "stdout_tail": (completed.stdout or "")[-4000:],
            },
            warnings=[
                "nnU-Net outputs remain external prediction artifacts until "
                "reviewed/imported into ReefVision."
            ],
        )
