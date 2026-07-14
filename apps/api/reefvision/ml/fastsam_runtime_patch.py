"""FastSAM prompt adapter layered onto the optional Smart Mask runtime."""

from __future__ import annotations

from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.ml.catalog_expansion import UnifiedSegmentAnythingAssistProvider
from reefvision.ml.providers import AssistPrediction, PixelBox, mask_to_box

_PATCHED = False
_ORIGINAL_PREDICT = UnifiedSegmentAnythingAssistProvider._predict


def _annotation_mask(annotation: Any) -> Any:
    import numpy

    if hasattr(annotation, "detach"):
        annotation = annotation.detach().float().cpu().numpy()
    array = numpy.asarray(annotation)
    while array.ndim > 2 and array.shape[0] == 1:
        array = array[0]
    if array.ndim == 3:
        areas = array.reshape(array.shape[0], -1).sum(axis=1)
        array = array[int(areas.argmax())]
    if array.ndim != 2:
        raise ValidationError("FastSAM returned an unsupported mask shape")
    mask = array > 0.5
    if not mask.any():
        raise ValidationError("FastSAM returned an empty mask")
    return mask


def _fastsam_predict(
    self: UnifiedSegmentAnythingAssistProvider,
    prepared_image: Any,
    *,
    points: list[list[float]] | None = None,
    labels: list[int] | None = None,
    box: PixelBox | None = None,
) -> AssistPrediction:
    if self._backend != "fastsam":
        return _ORIGINAL_PREDICT(
            self,
            prepared_image,
            points=points,
            labels=labels,
            box=box,
        )
    if self._model is None:
        raise ValidationError("The FastSAM model is not loaded")
    try:
        from ultralytics.models.fastsam import FastSAMPrompt

        results = self._model(
            str(prepared_image),
            device=self._device,
            retina_masks=True,
            verbose=False,
        )
        prompt = FastSAMPrompt(str(prepared_image), results, device=self._device)
        if points:
            annotation = prompt.point_prompt(
                points=points,
                pointlabel=labels or [1] * len(points),
            )
        elif box is not None:
            annotation = prompt.box_prompt(
                bbox=[box.x_min, box.y_min, box.x_max, box.y_max]
            )
        else:
            raise ValidationError("FastSAM requires point or box prompting")
        mask = _annotation_mask(annotation)
        return AssistPrediction(mask=mask, box=mask_to_box(mask), score=1.0)
    except ValidationError:
        raise
    except Exception as exc:  # pragma: no cover - depends on third-party runtime
        raise ValidationError(f"FastSAM prompting failed: {exc}") from exc


def apply_fastsam_runtime_patch() -> None:
    global _PATCHED
    if _PATCHED:
        return
    UnifiedSegmentAnythingAssistProvider._predict = _fastsam_predict  # type: ignore[method-assign]
    _PATCHED = True
