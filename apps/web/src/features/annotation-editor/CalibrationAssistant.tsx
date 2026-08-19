import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  applyMeasurementCalibrationProfile,
  detectMarkerCalibration,
  detectRulerCalibration,
  getMeasurementCalibrationProfiles,
  updateMeasurementCalibration,
  type MeasurementCalibration,
  type MarkerCalibrationCandidate,
  type RulerCalibrationCandidate,
} from "./maskMeasurementsApi";

interface CalibrationAssistantProps {
  projectId: string;
  imageId: string;
  defaultUnit: string;
  onApplied: (calibration: MeasurementCalibration) => Promise<void> | void;
}

function positiveNumber(value: string, label: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`${label} must be greater than zero`);
  }
  return parsed;
}

function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function CalibrationAssistant({
  projectId,
  imageId,
  defaultUnit,
  onApplied,
}: CalibrationAssistantProps) {
  const [unit, setUnit] = useState(defaultUnit || "mm");
  const [profileName, setProfileName] = useState("");
  const [rulerReferenceLength, setRulerReferenceLength] = useState("");
  const [rulerOrientation, setRulerOrientation] = useState<
    "auto" | "horizontal" | "vertical"
  >("auto");
  const [rulerCandidate, setRulerCandidate] =
    useState<RulerCalibrationCandidate | null>(null);
  const [markerKind, setMarkerKind] = useState<"aruco" | "charuco">("aruco");
  const [markerLength, setMarkerLength] = useState("");
  const [markerId, setMarkerId] = useState("");
  const [dictionary, setDictionary] = useState("DICT_4X4_50");
  const [charucoSquaresX, setCharucoSquaresX] = useState("5");
  const [charucoSquaresY, setCharucoSquaresY] = useState("7");
  const [charucoSquareLength, setCharucoSquareLength] = useState("");
  const [markerCandidate, setMarkerCandidate] =
    useState<MarkerCalibrationCandidate | null>(null);
  const [selectedProfileImageId, setSelectedProfileImageId] = useState("");
  const [confirmSameSetup, setConfirmSameSetup] = useState(false);

  useEffect(() => {
    setUnit(defaultUnit || "mm");
    setProfileName("");
    setRulerReferenceLength("");
    setRulerCandidate(null);
    setMarkerCandidate(null);
    setSelectedProfileImageId("");
    setConfirmSameSetup(false);
  }, [defaultUnit, imageId]);

  const profilesQuery = useQuery({
    queryKey: ["measurement-calibration-profiles", projectId],
    queryFn: ({ signal }) => getMeasurementCalibrationProfiles(projectId, signal),
    retry: false,
    refetchOnWindowFocus: false,
  });

  const availableProfiles = useMemo(
    () =>
      (profilesQuery.data ?? []).filter(
        (profile) => profile.source_image_id !== imageId,
      ),
    [imageId, profilesQuery.data],
  );

  const rulerDetectMutation = useMutation({
    mutationFn: () =>
      detectRulerCalibration(imageId, { orientation: rulerOrientation }),
    onSuccess: setRulerCandidate,
  });

  const rulerApplyMutation = useMutation({
    mutationFn: async () => {
      if (!rulerCandidate || rulerCandidate.image_id !== imageId) {
        throw new Error("Detect a ruler candidate for the current image first");
      }
      const referenceLength = positiveNumber(
        rulerReferenceLength,
        "Known ruler interval",
      );
      if (!unit.trim()) throw new Error("A physical unit is required");
      return updateMeasurementCalibration(imageId, {
        distance_per_pixel:
          referenceLength / rulerCandidate.base_interval_pixels,
        unit: unit.trim(),
        source: "automatic_ruler",
        reference_length: referenceLength,
        reference_pixel_length: rulerCandidate.base_interval_pixels,
        confidence: rulerCandidate.confidence,
        detector: "reefvision-ruler-periodicity-v1",
        profile_name: profileName.trim() || null,
        reference_plane_only: false,
        notes:
          "Automatic ruler tick spacing was reviewed by the researcher; the physical interval and unit were supplied manually.",
      });
    },
    onSuccess: async (calibration) => {
      await onApplied(calibration);
      await profilesQuery.refetch();
    },
  });

  const markerDetectMutation = useMutation({
    mutationFn: () => {
      const physicalMarkerLength = positiveNumber(
        markerLength,
        "Marker length",
      );
      if (!unit.trim()) throw new Error("A physical unit is required");
      const parsedMarkerId = markerId.trim() ? Number(markerId) : null;
      if (
        parsedMarkerId != null &&
        (!Number.isInteger(parsedMarkerId) || parsedMarkerId < 0)
      ) {
        throw new Error("Marker ID must be a non-negative integer");
      }
      return detectMarkerCalibration(imageId, {
        kind: markerKind,
        unit: unit.trim(),
        dictionary: dictionary.trim() || "DICT_4X4_50",
        marker_length: physicalMarkerLength,
        marker_id: parsedMarkerId,
        charuco_squares_x:
          markerKind === "charuco"
            ? positiveNumber(charucoSquaresX, "ChArUco squares X")
            : null,
        charuco_squares_y:
          markerKind === "charuco"
            ? positiveNumber(charucoSquaresY, "ChArUco squares Y")
            : null,
        charuco_square_length:
          markerKind === "charuco"
            ? positiveNumber(charucoSquareLength, "ChArUco square length")
            : null,
      });
    },
    onSuccess: setMarkerCandidate,
  });

  const markerApplyMutation = useMutation({
    mutationFn: async () => {
      if (!markerCandidate || markerCandidate.image_id !== imageId) {
        throw new Error("Detect a marker candidate for the current image first");
      }
      return updateMeasurementCalibration(imageId, {
        ...markerCandidate.calibration,
        profile_name: profileName.trim() || null,
      });
    },
    onSuccess: async (calibration) => {
      await onApplied(calibration);
      await profilesQuery.refetch();
    },
  });

  const profileApplyMutation = useMutation({
    mutationFn: async () => {
      if (!selectedProfileImageId) {
        throw new Error("Select a saved calibration profile");
      }
      if (!confirmSameSetup) {
        throw new Error(
          "Confirm that camera, lens, focus, mount distance, and measurement plane are unchanged",
        );
      }
      return applyMeasurementCalibrationProfile(imageId, {
        source_image_id: selectedProfileImageId,
        confirm_same_setup: true,
      });
    },
    onSuccess: onApplied,
  });

  const currentError =
    rulerDetectMutation.error ??
    rulerApplyMutation.error ??
    markerDetectMutation.error ??
    markerApplyMutation.error ??
    profileApplyMutation.error ??
    profilesQuery.error;

  return (
    <div data-testid="calibration-assistant">
      <p className="annotation-helper">
        Scale Assistant proposes calibration evidence but keeps the researcher in
        control. Ruler detection never guesses the physical unit or interval.
      </p>

      <label>
        Physical unit
        <input
          value={unit}
          onChange={(event) => setUnit(event.target.value)}
          placeholder="mm"
        />
      </label>
      <label>
        Save accepted calibration as profile (optional)
        <input
          value={profileName}
          onChange={(event) => setProfileName(event.target.value)}
          placeholder="Camera stand at fixed distance"
        />
      </label>

      <details>
        <summary>Detect ruler spacing</summary>
        <label>
          Ruler orientation
          <select
            value={rulerOrientation}
            onChange={(event) =>
              setRulerOrientation(
                event.target.value as "auto" | "horizontal" | "vertical",
              )
            }
          >
            <option value="auto">Auto</option>
            <option value="horizontal">Horizontal</option>
            <option value="vertical">Vertical</option>
          </select>
        </label>
        <button
          type="button"
          className="secondary"
          onClick={() => rulerDetectMutation.mutate()}
          disabled={rulerDetectMutation.isPending}
        >
          {rulerDetectMutation.isPending ? "Detecting..." : "Detect ruler"}
        </button>
        {rulerCandidate && (
          <>
            <div className="annotation-selection-row">
              <strong>Detected interval</strong>
              <span>{rulerCandidate.base_interval_pixels.toFixed(3)} px</span>
            </div>
            <div className="annotation-selection-row">
              <strong>Confidence</strong>
              <span>{formatConfidence(rulerCandidate.confidence)}</span>
            </div>
            <div className="annotation-selection-row">
              <strong>Repeated intervals</strong>
              <span>{rulerCandidate.interval_count}</span>
            </div>
            <label>
              Known physical length of one detected interval
              <input
                type="number"
                min="0"
                step="any"
                value={rulerReferenceLength}
                onChange={(event) => setRulerReferenceLength(event.target.value)}
                placeholder="10"
              />
            </label>
            {rulerCandidate.warnings.length > 0 && (
              <ul className="system-details">
                {rulerCandidate.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}
            <button
              type="button"
              className="secondary"
              onClick={() => rulerApplyMutation.mutate()}
              disabled={rulerApplyMutation.isPending}
            >
              {rulerApplyMutation.isPending
                ? "Applying..."
                : "Apply reviewed ruler scale"}
            </button>
          </>
        )}
      </details>

      <details>
        <summary>Detect ArUco / ChArUco</summary>
        <label>
          Reference type
          <select
            value={markerKind}
            onChange={(event) => {
              setMarkerKind(event.target.value as "aruco" | "charuco");
              setMarkerCandidate(null);
            }}
          >
            <option value="aruco">ArUco marker</option>
            <option value="charuco">ChArUco board</option>
          </select>
        </label>
        <label>
          Dictionary
          <input
            value={dictionary}
            onChange={(event) => setDictionary(event.target.value)}
          />
        </label>
        <label>
          Marker side length
          <input
            type="number"
            min="0"
            step="any"
            value={markerLength}
            onChange={(event) => setMarkerLength(event.target.value)}
          />
        </label>
        {markerKind === "aruco" ? (
          <label>
            Marker ID (optional)
            <input
              type="number"
              min="0"
              step="1"
              value={markerId}
              onChange={(event) => setMarkerId(event.target.value)}
            />
          </label>
        ) : (
          <>
            <label>
              ChArUco squares X
              <input
                type="number"
                min="2"
                step="1"
                value={charucoSquaresX}
                onChange={(event) => setCharucoSquaresX(event.target.value)}
              />
            </label>
            <label>
              ChArUco squares Y
              <input
                type="number"
                min="2"
                step="1"
                value={charucoSquaresY}
                onChange={(event) => setCharucoSquaresY(event.target.value)}
              />
            </label>
            <label>
              ChArUco square length
              <input
                type="number"
                min="0"
                step="any"
                value={charucoSquareLength}
                onChange={(event) => setCharucoSquareLength(event.target.value)}
              />
            </label>
          </>
        )}
        <button
          type="button"
          className="secondary"
          onClick={() => markerDetectMutation.mutate()}
          disabled={markerDetectMutation.isPending}
        >
          {markerDetectMutation.isPending ? "Detecting..." : "Detect marker"}
        </button>
        {markerCandidate && (
          <>
            <div className="annotation-selection-row">
              <strong>Detected corners</strong>
              <span>{markerCandidate.detected_corner_count}</span>
            </div>
            <div className="annotation-selection-row">
              <strong>Confidence</strong>
              <span>{formatConfidence(markerCandidate.confidence)}</span>
            </div>
            <p className="annotation-helper">
              Perspective correction applies only to measurements lying on the
              detected physical reference plane.
            </p>
            <button
              type="button"
              className="secondary"
              onClick={() => markerApplyMutation.mutate()}
              disabled={markerApplyMutation.isPending}
            >
              {markerApplyMutation.isPending
                ? "Applying..."
                : "Apply marker calibration"}
            </button>
          </>
        )}
      </details>

      <details>
        <summary>Reuse a saved camera/setup profile</summary>
        {profilesQuery.isPending ? (
          <p className="annotation-helper">Loading calibration profiles...</p>
        ) : availableProfiles.length === 0 ? (
          <p className="annotation-helper">
            No reusable calibration profiles are available for this project yet.
          </p>
        ) : (
          <>
            <label>
              Calibration profile
              <select
                value={selectedProfileImageId}
                onChange={(event) => {
                  setSelectedProfileImageId(event.target.value);
                  setConfirmSameSetup(false);
                }}
              >
                <option value="">Select a profile</option>
                {availableProfiles.map((profile) => (
                  <option
                    key={profile.source_image_id}
                    value={profile.source_image_id}
                  >
                    {profile.profile_name} — {profile.distance_per_pixel.toPrecision(5)} {profile.unit}/px ({profile.width_px}×{profile.height_px})
                  </option>
                ))}
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                checked={confirmSameSetup}
                onChange={(event) => setConfirmSameSetup(event.target.checked)}
              />{" "}
              I confirm camera, lens, focus, mount distance, image resolution,
              and measurement plane are unchanged.
            </label>
            <button
              type="button"
              className="secondary"
              onClick={() => profileApplyMutation.mutate()}
              disabled={
                !selectedProfileImageId ||
                !confirmSameSetup ||
                profileApplyMutation.isPending
              }
            >
              {profileApplyMutation.isPending
                ? "Applying..."
                : "Apply saved profile"}
            </button>
          </>
        )}
      </details>

      {currentError instanceof Error && (
        <p className="form-error">{currentError.message}</p>
      )}
    </div>
  );
}
