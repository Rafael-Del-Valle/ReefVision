import { videoGeographicExportUrl } from "./videoGeographicExportApi";

interface GeographicExportPanelProps {
  videoId: string | null;
  selectedTrackId?: string | null;
}

export function GeographicExportPanel({
  videoId,
  selectedTrackId = null,
}: GeographicExportPanelProps) {
  const normalizedVideoId = videoId?.trim() || null;
  const normalizedTrackId = selectedTrackId?.trim() || null;

  return (
    <section className="management-card" data-testid="geographic-export-panel">
      <p className="eyebrow">GIS interoperability</p>
      <h3>Geographic export</h3>

      <p className="annotation-helper">
        Export persisted geographic observations for GIS analysis. GeoJSON
        includes observation points and track LineStrings; CSV contains one
        persisted observation per row. Exporting does not recalculate
        coordinates.
      </p>

      {!normalizedVideoId ? (
        <p className="annotation-helper">
          Select a video to enable geographic exports.
        </p>
      ) : (
        <>
          <div className="annotation-editor-inline-actions">
            <a
              className="secondary"
              href={videoGeographicExportUrl(normalizedVideoId, "geojson")}
              download="reefvision-geographic-observations.geojson"
            >
              Download whole-video GeoJSON
            </a>

            <a
              className="secondary"
              href={videoGeographicExportUrl(normalizedVideoId, "csv")}
              download="reefvision-geographic-observations.csv"
            >
              Download whole-video CSV
            </a>
          </div>

          <div style={{ marginTop: 12 }}>
            <p className="annotation-helper">
              {normalizedTrackId
                ? "Selected-track export uses only persisted observations linked to the selected track."
                : "Select a track to enable track-filtered GIS exports."}
            </p>

            {normalizedTrackId && (
              <div className="annotation-editor-inline-actions">
                <a
                  className="secondary"
                  href={videoGeographicExportUrl(
                    normalizedVideoId,
                    "geojson",
                    normalizedTrackId,
                  )}
                  download="reefvision-selected-track.geojson"
                >
                  Download selected-track GeoJSON
                </a>

                <a
                  className="secondary"
                  href={videoGeographicExportUrl(
                    normalizedVideoId,
                    "csv",
                    normalizedTrackId,
                  )}
                  download="reefvision-selected-track.csv"
                >
                  Download selected-track CSV
                </a>
              </div>
            )}
          </div>

          <p className="annotation-helper" style={{ marginTop: 12 }}>
            Track classes are linked from authoritative persisted track records
            when available. Confidence is exported only for an exact persisted
            keyframe; interpolated observations remain explicitly empty. No
            class, confidence, coordinate, or accuracy value is inferred during
            export.
          </p>
        </>
      )}
    </section>
  );
}
