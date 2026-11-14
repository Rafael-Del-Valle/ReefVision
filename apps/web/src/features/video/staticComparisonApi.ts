import { request } from "../../api/client";

export const staticComparisonPath = (projectId: string) =>
  `/projects/${projectId}/static-comparisons`;

export type StaticLineage = "held_out" | "exploratory" | "overlap";

export const staticLineageLabels: Record<StaticLineage, string> = {
  held_out: "Held-out under recorded lineage",
  exploratory: "Exploratory · independence unverified",
  overlap: "Exploratory · known reference overlap",
};

type ReferenceClass = { id: string; name: string };

export interface StaticOptions {
  datasets: {
    id: string;
    name: string;
    reviewed_count: number;
    test_reviewed_count: number;
    classes: ReferenceClass[];
  }[];
  models: { id: string; name: string; mapped_class_ids: string[] }[];
}

export interface StaticSummary {
  id: string;
  status: string;
  created_at: string;
  reference_name: string;
  model_names: string[];
  evaluation_status: StaticLineage | null;
}

export const listStaticComparisons = (
  projectId: string,
  limit: number,
  offset: number,
  signal?: AbortSignal,
  completedOnly = false,
) =>
  request<StaticSummary[]>(
    `${staticComparisonPath(projectId)}?limit=${limit}&offset=${offset}${completedOnly ? "&completed_only=true" : ""}`,
    { signal },
  );

export interface StaticComparisonConfiguration {
  dataset_version_id: string;
  model_ids: string[];
  split: "test" | "all";
  class_ids: string[];
  inference: {
    confidence_threshold: number;
    iou_threshold: number;
    device: "auto" | "cpu" | "cuda";
  };
  independent_groups: boolean;
  homoscedastic_normal_differences: boolean;
  icc: "A,1" | "C,1" | null;
}

type Interval = [number, number] | null;
export interface StaticStatistics {
  observation_count: number;
  frozen_group_count: number;
  independent_group_count: number | null;
  ungrouped_observation_count: number;
  zero_reference_count: number;
  percentage_denominator: number;
  bias: number | null;
  mean_absolute_error: number | null;
  root_mean_squared_error: number | null;
  mean_absolute_percentage_error: number | null;
  mean_signed_percentage_error: number | null;
  limits_of_agreement: Interval;
  icc: number | null;
  bias_ci95: Interval;
  mae_ci95: Interval;
}

type PairedDifference = Pick<
  StaticStatistics,
  | "observation_count"
  | "frozen_group_count"
  | "independent_group_count"
  | "ungrouped_observation_count"
> & {
  absolute_error_change: number | null;
  absolute_error_change_ci95: Interval;
};

export interface StaticComparisonRecord {
  id: string;
  stale: boolean;
  source_id_map: Record<string, string>;
  content_sha256: string;
  snapshot: {
    method: string;
    evaluation_status: StaticLineage;
    evidence: {
      options: StaticComparisonConfiguration;
      reference_name: string;
      reference_sha256: string;
      outside_split_image_count: number;
      classes: ReferenceClass[];
      images: {
        id: string;
        name: string;
        group_key: string | null;
        split: string;
      }[];
      models: {
        id: string;
        name: string;
        checkpoint_sha256: string;
        provider_name: string;
        lineage: {
          status: StaticLineage;
          reasons: string[];
          overlapping_image_ids: string[];
        };
      }[];
    };
    results: {
      model_id: string;
      runtime_provider_version: string | null;
      total_statistics: StaticStatistics;
      class_statistics: Record<string, StaticStatistics>;
      images: {
        image_id: string;
        status: string;
        message: string | null;
        counts: {
          class_id: string;
          reference: number;
          prediction: number | null;
          status: string;
        }[];
      }[];
    }[];
    total_model_difference: PairedDifference | null;
    class_model_differences: Record<string, PairedDifference>;
    limitations: string[];
  };
}
