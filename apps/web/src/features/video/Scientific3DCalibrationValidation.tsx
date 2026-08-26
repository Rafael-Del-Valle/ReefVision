import { useMemo, useState } from "react";

import {
  validateMetricDepth3DCalibration,
  type MetricVideoDepth3DResult,
} from "./videoScienceApi";

interface Scientific3DCalibrationValidationProps {
  videoId: string;
  jobId: string;
  result: MetricVideoDepth3DResult;
  onResultUpdated: (result: MetricVideoDepth3DResult) => void;
}

interface ParsedReference {
  track_id: string;
  frame: number;
  expected_depth_m: number;
}

function parseReferences(text: string): ParsedReference[] {
  const rows = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  return rows.map((line, index) => {
    const columns = line.split(",").map((value) => value.trim());
    if (columns.length !== 3) {
      throw new Error(
        `Reference line ${index + 1} must be track_id,frame,expected_depth_m`,
      );
    }
    const frame = Number.parseInt(columns[1], 10);
    const expected = Number(columns[2]);
    if (!columns[0] || !Number.isInteger(frame) || frame < 0) {
      throw new Error(`Reference line ${index + 1} has an invalid track/frame`);
    }
    if (!Number.isFinite(expected) || expected <= 0) {
      throw new Error(
        `Reference line ${index + 1} needs a positive depth in meters`,
      );
    }
    return {
      track_id: columns[0],
      frame,
      expected_depth_m: expected,
    };
  });
}

export function Scientific3DCalibrationValidation({
  videoId,
  jobId,
  result,
  onResultUpdated,
}: Scientific3DCalibrationValidationProps) {
  const [referenceSource, setReferenceSource] = useState("");
  const [referenceMethod, setReferenceMethod] = useState("");
  const [setupDescription, setSetupDescription] = useState("");
  const [relativePercent, setRelativePercent] = useState(5);
  const [absoluteCm, setAbsoluteCm] = useState(2);
  const [referenceText, setReferenceText] = useState("");
  const [independentConfirmed, setIndependentConfirmed] = useState(false);
  const [sameSetupConfirmed, setSameSetupConfirmed] = useState(false);
  const [underwaterConfirmed, setUnderwaterConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const validation = result.calibration_validation;
  const example = useMemo(() => {
    const track = result.analytics.tracks[0];
    if (!track || track.points.length === 0) return null;
    const indices = [0, 0.25, 0.5, 0.75, 1].map((fraction) =>
      Math.min(
        track.points.length - 1,
        Math.round((track.points.length - 1) * fraction),
      ),
    );
    const unique = [...new Set(indices)].map((index) => track.points[index]);
    return unique
      .map((point) => `${track.track_id},${point.frame},`)
      .join("\n");
  }, [result.analytics.tracks]);

  async function submit() {
    setMessage(null);
    try {
      const references = parseReferences(referenceText);
      setPending(true);
      const updated = await validateMetricDepth3DCalibration(videoId, jobId, {
        reference_source: referenceSource,
        reference_method: referenceMethod,
        setup_description: setupDescription,
        reference_samples: references,
        relative_tolerance: relativePercent / 100,
        absolute_tolerance_m: absoluteCm / 100,
        independent_reference_confirmed: independentConfirmed,
        same_optical_setup_confirmed: sameSetupConfirmed,
        underwater_environment_confirmed: underwaterConfirmed,
      });
      onResultUpdated(updated);
      setMessage(
        updated.depth_tier === "calibrated_metric"
          ? "Validation passed. This run is now calibrated metric."
          : "Validation did not meet the physical-measurement qualification criteria.",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setPending(false);
    }
  }

  return (
    <section
      className="panel-card"
      data-testid="scientific-3d-calibration-validation"
    >
      <p className="eyebrow">Underwater physical validation</p>
      <h4>Promote model-estimated depth to calibrated metric</h4>
      <p className="annotation-helper">
        ReefVision only promotes this specific Scientific 3D run when raw VDA
        depths agree with independently measured underwater reference depths.
        The validation data are not used to fit or correct the model.
      </p>

      <label>
        Independent reference source
        <input
          value={referenceSource}
          onChange={(event) => setReferenceSource(event.target.value)}
          placeholder="e.g. calibrated stereo rig or measured tank target positions"
        />
      </label>

      <label>
        Reference measurement method
        <input
          value={referenceMethod}
          onChange={(event) => setReferenceMethod(event.target.value)}
          placeholder="e.g. stereo triangulation with calibrated baseline"
        />
      </label>

      <label>
        Optical setup description
        <textarea
          value={setupDescription}
          onChange={(event) => setSetupDescription(event.target.value)}
          placeholder="Camera, housing/port, water conditions, target arrangement, and working range"
        />
      </label>

      <label>
        Independent reference depths
        <textarea
          aria-label="Independent reference depths"
          value={referenceText}
          onChange={(event) => setReferenceText(event.target.value)}
          placeholder={
            example
              ? `track_id,frame,expected_depth_m\n${example}`
              : "track_id,frame,expected_depth_m"
          }
          rows={8}
        />
      </label>
      <p className="annotation-helper">
        Minimum: 5 samples across at least 3 frames and at least 0.05 m of
        independently measured depth range. Do not copy ReefVision/VDA
        predictions into the expected-depth column.
      </p>

      <div className="annotation-selection-list">
        <label>
          Relative tolerance (%; maximum 10)
          <input
            type="number"
            min={0}
            max={10}
            step={0.5}
            value={relativePercent}
            onChange={(event) => setRelativePercent(Number(event.target.value))}
          />
        </label>
        <label>
          Absolute tolerance (cm; maximum 5)
          <input
            type="number"
            min={0}
            max={5}
            step={0.5}
            value={absoluteCm}
            onChange={(event) => setAbsoluteCm(Number(event.target.value))}
          />
        </label>
      </div>

      <label>
        <input
          type="checkbox"
          checked={independentConfirmed}
          onChange={(event) => setIndependentConfirmed(event.target.checked)}
        />
        Reference depths were measured independently of ReefVision/VDA output.
      </label>
      <label>
        <input
          type="checkbox"
          checked={sameSetupConfirmed}
          onChange={(event) => setSameSetupConfirmed(event.target.checked)}
        />
        Reference data use the same camera, housing/port, and optical setup.
      </label>
      <label>
        <input
          type="checkbox"
          checked={underwaterConfirmed}
          onChange={(event) => setUnderwaterConfirmed(event.target.checked)}
        />
        Validation reference data were acquired underwater.
      </label>

      <button
        type="button"
        disabled={
          pending ||
          !referenceSource.trim() ||
          !referenceMethod.trim() ||
          !setupDescription.trim() ||
          !referenceText.trim() ||
          !independentConfirmed ||
          !sameSetupConfirmed ||
          !underwaterConfirmed
        }
        onClick={() => void submit()}
      >
        {pending ? "Validating..." : "Validate physical depth"}
      </button>

      {message && <p className="annotation-helper">{message}</p>}

      {validation && (
        <div className="annotation-selection-list">
          <div className="annotation-selection-row">
            <strong>Qualification</strong>
            <span>{validation.qualified ? "Passed" : "Not qualified"}</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Samples / frames</strong>
            <span>
              {validation.sample_count} / {validation.distinct_frame_count}
            </span>
          </div>
          <div className="annotation-selection-row">
            <strong>Reference depth span</strong>
            <span>{validation.reference_depth_span_m.toFixed(3)} m</span>
          </div>
          <div className="annotation-selection-row">
            <strong>RMSE</strong>
            <span>{validation.rmse_m.toFixed(4)} m</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Mean relative error</strong>
            <span>{(validation.mean_relative_error * 100).toFixed(2)}%</span>
          </div>
          <div className="annotation-selection-row">
            <strong>Depth correction fitted</strong>
            <span>No</span>
          </div>
        </div>
      )}
    </section>
  );
}
