import { importImages, request, type ProjectImage } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";

export interface BandDraft {
  name: string;
  wavelength: string;
  image: ProjectImage;
  dx: string;
  dy: string;
  nodata: string;
  calibrated: boolean;
  dark: string;
  white: string;
  reflectance: string;
  reference: string;
}
interface Calibration {
  dark_dn: number;
  white_dn: number;
  white_reflectance: number;
  reference: string;
}
export interface Band {
  name: string;
  wavelength_nm: number;
  image_id: string;
  original_sha256: string;
  width: number;
  height: number;
  bits: number;
  offset_x: number;
  offset_y: number;
  nodata: number | null;
  calibration: Calibration | null;
}
export interface Alignment {
  grid: string;
  reviewer: string;
  evidence: string;
  maximum_residual_px: number;
}
export interface Capture {
  source_project_id: string;
  label: string;
  sensor: string;
  alignment: Alignment | null;
  bands: Band[];
}
export interface Index {
  acquisition: Capture;
  selection: { acquisition_sha256: string; positive: number; negative: number };
  result: {
    status: "available" | "withheld";
    reasons: string[];
    reference_pixels: number;
    valid_pixels: number;
    excluded: {
      outside_grid: number;
      invalid_band_sample: number;
      zero_denominator: number;
    };
    minimum: number | null;
    maximum: number | null;
    mean: number | null;
    float32_le_sha256: string | null;
    mask_sha256: string | null;
  };
}
export interface Receipt<T> {
  id: string;
  project_id: string;
  content_sha256: string;
  created_at: string;
  snapshot: T;
}
export interface Page<T> {
  items: Receipt<T>[];
  total: number;
}
const root = (project: string) =>
  `/projects/${encodeURIComponent(project)}/multispectral`;
export const spectralUrl = (project: string, suffix: string) =>
  getApiBaseUrl() + root(project) + suffix;
export function spectralList<T>(
  project: string,
  kind: "acquisitions" | "indices",
  offset: number,
  signal?: AbortSignal,
) {
  return request<Page<T>>(
    root(project) + `/${kind}?limit=25&offset=${offset}`,
    { signal },
  );
}

export async function importBands(
  project: string,
  files: File[],
): Promise<BandDraft[]> {
  if (files.length < 2 || files.length > 8)
    throw new Error("Choose between two and eight original band files.");
  const imported = await importImages(project, files);
  const problem = [...imported.failed, ...imported.unsupported][0];
  if (problem) throw new Error(`${problem.filename}: ${problem.detail}`);
  return Promise.all(
    files.map(async (file) => {
      const source = [...imported.successful, ...imported.duplicates].find(
        (row) => row.relative_path === file.name,
      );
      const id = source?.image_id ?? source?.duplicate_image_id;
      if (!id)
        throw new Error(
          `Could not identify the imported source for ${file.name}.`,
        );
      const image = await request<ProjectImage>("/images/" + id);
      return {
        name: file.name.replace(/\.[^.]+$/, ""),
        wavelength: "",
        image,
        dx: "0",
        dy: "0",
        nodata: "",
        calibrated: false,
        dark: "",
        white: "",
        reflectance: "1",
        reference: "",
      };
    }),
  );
}

export function saveAcquisition(
  project: string,
  label: string,
  sensor: string,
  alignment: Alignment | null,
  bands: BandDraft[],
) {
  return request<Receipt<Capture>>(root(project) + "/acquisitions", {
    method: "POST",
    body: JSON.stringify({
      label,
      sensor,
      alignment,
      bands: bands.map((b) => ({
        name: b.name,
        wavelength_nm: Number(b.wavelength),
        image_id: b.image.id,
        original_sha256: b.image.sha256,
        offset_x: Number(b.dx),
        offset_y: Number(b.dy),
        nodata: b.nodata === "" ? null : Number(b.nodata),
        calibration: b.calibrated
          ? {
              dark_dn: Number(b.dark),
              white_dn: Number(b.white),
              white_reflectance: Number(b.reflectance),
              reference: b.reference,
            }
          : null,
      })),
    }),
  });
}
export function computeIndex(
  project: string,
  acquisition: Receipt<Capture>,
  positive: number,
  negative: number,
) {
  return request<Receipt<Index>>(
    root(project) + "/acquisitions/" + acquisition.id + "/indices",
    {
      method: "POST",
      body: JSON.stringify({
        acquisition_sha256: acquisition.content_sha256,
        positive,
        negative,
      }),
    },
  );
}
export function saveIndexGraph(record: Receipt<Index>) {
  return saveWorkflowGraph(record.project_id, {
    graph_id: "spectral-" + record.id,
    name: "Spectral index · " + record.snapshot.acquisition.label,
    nodes: [
      { node_id: "project", node_type: "project_source" },
      {
        node_id: "index",
        node_type: "multispectral_index",
        parameters: {
          index_id: record.id,
          content_sha256: record.content_sha256,
        },
      },
    ],
    edges: [
      {
        edge_id: "project-index",
        source_node_id: "project",
        source_port_id: "project",
        target_node_id: "index",
        target_port_id: "project",
      },
    ],
  });
}
