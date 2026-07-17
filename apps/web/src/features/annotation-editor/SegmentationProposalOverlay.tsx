import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { getApiBaseUrl } from "../../runtime";

interface SegmentationProposal {
  id: string;
  geometry_kind?: string;
  polygon_json?: number[][] | null;
  predicted_label: string;
  confidence: number;
  x_min: number;
  y_min: number;
}

interface PredictionListResponse {
  items: SegmentationProposal[];
}

interface OverlayTarget {
  imageId: string;
  group: SVGGElement;
}

function currentOverlayTarget(): OverlayTarget | null {
  const canvas = document.querySelector<SVGSVGElement>(
    "svg.annotation-canvas",
  );
  const group = canvas?.querySelector<SVGGElement>(":scope > g") ?? null;
  const image =
    group?.querySelector<SVGImageElement>(":scope > image") ?? null;
  const href =
    image?.getAttribute("href") ??
    image?.getAttribute("xlink:href") ??
    "";
  const match = href.match(
    /\/images\/([^/]+)\/(?:content|thumbnail)(?:\?|$)/,
  );
  if (!group || !match?.[1]) {
    return null;
  }
  return { imageId: decodeURIComponent(match[1]), group };
}

async function loadSegmentationProposals(
  imageId: string,
  signal: AbortSignal,
): Promise<SegmentationProposal[]> {
  const response = await fetch(
    `${getApiBaseUrl()}/images/${encodeURIComponent(imageId)}/prediction-proposals?review_status=pending`,
    { signal },
  );
  if (!response.ok) {
    throw new Error(
      `Prediction overlay request failed with HTTP ${response.status}`,
    );
  }
  const payload = (await response.json()) as PredictionListResponse;
  return payload.items.filter(
    (proposal) =>
      proposal.geometry_kind === "polygon_mask" &&
      Array.isArray(proposal.polygon_json) &&
      proposal.polygon_json.length >= 3,
  );
}

export function SegmentationProposalOverlay() {
  const [target, setTarget] = useState<OverlayTarget | null>(null);
  const [proposals, setProposals] = useState<SegmentationProposal[]>([]);

  useEffect(() => {
    const updateTarget = () => {
      const next = currentOverlayTarget();
      setTarget((current) =>
        current?.imageId === next?.imageId && current?.group === next?.group
          ? current
          : next,
      );
    };
    updateTarget();
    const observer = new MutationObserver(updateTarget);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!target) {
      setProposals([]);
      return;
    }
    let controller: AbortController | null = null;
    let stopped = false;
    const refresh = async () => {
      controller?.abort();
      const nextController = new AbortController();
      controller = nextController;
      try {
        const items = await loadSegmentationProposals(
          target.imageId,
          nextController.signal,
        );
        if (!stopped) {
          setProposals(items);
        }
      } catch (error) {
        if (!nextController.signal.aborted && !stopped) {
          console.warn(
            "Segmentation proposal overlay could not refresh",
            error,
          );
        }
      }
    };
    void refresh();
    const interval = window.setInterval(() => void refresh(), 2000);
    return () => {
      stopped = true;
      controller?.abort();
      window.clearInterval(interval);
    };
  }, [target]);

  const overlay = useMemo(
    () =>
      proposals.map((proposal) => {
        const points = (proposal.polygon_json ?? [])
          .map(([x, y]) => `${Number(x)},${Number(y)}`)
          .join(" ");
        return (
          <g
            key={`segmentation-proposal-${proposal.id}`}
            data-segmentation-proposal-id={proposal.id}
            pointerEvents="none"
          >
            <polygon
              points={points}
              fill="rgba(245, 197, 66, 0.14)"
              stroke="#f5c542"
              strokeWidth={2}
              strokeDasharray="7 4"
              vectorEffect="non-scaling-stroke"
            />
            <text
              x={proposal.x_min + 4}
              y={proposal.y_min + 14}
              fill="#f5c542"
              fontSize={12}
            >
              {`${proposal.predicted_label} mask ${proposal.confidence.toFixed(2)}`}
            </text>
          </g>
        );
      }),
    [proposals],
  );

  return target ? createPortal(overlay, target.group) : null;
}
