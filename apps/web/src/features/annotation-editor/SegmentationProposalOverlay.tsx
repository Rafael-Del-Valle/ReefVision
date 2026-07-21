import type { PointerEvent } from "react";

import {
  predictionMaskContentUrl,
  type PredictionProposal,
} from "../../api/client";

interface PredictionProposalOverlayProps {
  proposal: PredictionProposal;
  imageWidth: number;
  imageHeight: number;
  color: string;
  selected: boolean;
  highlighted: boolean;
  strokeScale: number;
  onSelect: () => void;
}

function isValidPolygon(points: number[][] | null): points is number[][] {
  return Boolean(
    points &&
    points.length >= 3 &&
    points.every(
      (point) =>
        point.length === 2 &&
        Number.isFinite(point[0]) &&
        Number.isFinite(point[1]),
    ),
  );
}

export function PredictionProposalOverlay({
  proposal,
  imageWidth,
  imageHeight,
  color,
  selected,
  highlighted,
  strokeScale,
  onSelect,
}: PredictionProposalOverlayProps) {
  const kind = proposal.geometry_kind || "bounding_box";
  const width = Math.max(proposal.x_max - proposal.x_min, 1);
  const height = Math.max(proposal.y_max - proposal.y_min, 1);
  const strokeWidth = highlighted ? 2.5 : selected ? 2.25 : 1.5;
  const select = (event: PointerEvent<SVGGElement>) => {
    event.stopPropagation();
    onSelect();
  };
  const label = (
    <text
      x={proposal.x_min + 4 * strokeScale}
      y={proposal.y_min + 14 * strokeScale}
      fill={color}
      fontSize={12 * strokeScale}
      pointerEvents="none"
    >
      {`${proposal.predicted_label} ${proposal.confidence.toFixed(2)}`}
    </text>
  );

  if (kind === "polygon_mask" && isValidPolygon(proposal.polygon_json)) {
    return (
      <g
        data-testid={`prediction-geometry-${proposal.id}`}
        data-geometry-kind={kind}
        onPointerDown={select}
        style={{ cursor: "pointer" }}
      >
        <polygon
          data-testid={`prediction-polygon-${proposal.id}`}
          points={proposal.polygon_json.map(([x, y]) => `${x},${y}`).join(" ")}
          fill={color}
          fillOpacity={selected ? 0.36 : highlighted ? 0.3 : 0.18}
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={`${6 * strokeScale} ${4 * strokeScale}`}
          vectorEffect="non-scaling-stroke"
        />
        {label}
      </g>
    );
  }

  if (kind === "raster_mask" && proposal.mask_path) {
    const maskId = `prediction-mask-${proposal.id.replace(
      /[^a-zA-Z0-9_-]/g,
      "_",
    )}`;
    return (
      <g
        data-testid={`prediction-geometry-${proposal.id}`}
        data-geometry-kind={kind}
        onPointerDown={select}
        style={{ cursor: "pointer" }}
      >
        <defs>
          <mask
            id={maskId}
            maskUnits="userSpaceOnUse"
            width={imageWidth}
            height={imageHeight}
          >
            <image
              data-testid={`prediction-raster-source-${proposal.id}`}
              href={predictionMaskContentUrl(proposal.id)}
              width={imageWidth}
              height={imageHeight}
              preserveAspectRatio="none"
            />
          </mask>
        </defs>
        <rect
          data-testid={`prediction-raster-${proposal.id}`}
          width={imageWidth}
          height={imageHeight}
          fill={color}
          fillOpacity={selected ? 0.5 : highlighted ? 0.44 : 0.32}
          mask={`url(#${maskId})`}
          pointerEvents="none"
        />
        <rect
          x={proposal.x_min}
          y={proposal.y_min}
          width={width}
          height={height}
          fill="transparent"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={`${6 * strokeScale} ${4 * strokeScale}`}
          vectorEffect="non-scaling-stroke"
        />
        {label}
      </g>
    );
  }

  const invalidMask = kind !== "bounding_box";
  return (
    <g
      data-testid={`prediction-geometry-${proposal.id}`}
      data-geometry-kind={kind}
      data-invalid-geometry={invalidMask || undefined}
      onPointerDown={select}
      style={{ cursor: "pointer" }}
    >
      <rect
        data-testid={
          invalidMask
            ? `prediction-invalid-${proposal.id}`
            : `prediction-bbox-${proposal.id}`
        }
        x={proposal.x_min}
        y={proposal.y_min}
        width={width}
        height={height}
        fill={
          invalidMask
            ? "rgba(255, 107, 107, 0.08)"
            : selected
              ? "rgba(255, 196, 0, 0.14)"
              : highlighted
                ? "rgba(255, 196, 0, 0.16)"
                : "rgba(255, 196, 0, 0.06)"
        }
        stroke={invalidMask ? "#ff6b6b" : color}
        strokeWidth={strokeWidth}
        strokeDasharray={`${6 * strokeScale} ${4 * strokeScale}`}
        vectorEffect="non-scaling-stroke"
      />
      {invalidMask ? (
        <text
          x={proposal.x_min + 4 * strokeScale}
          y={proposal.y_min + 14 * strokeScale}
          fill="#ff6b6b"
          fontSize={12 * strokeScale}
          pointerEvents="none"
        >
          {`${proposal.predicted_label} mask geometry unavailable`}
        </text>
      ) : (
        label
      )}
    </g>
  );
}
