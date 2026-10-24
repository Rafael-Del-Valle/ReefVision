import { describe, expect, it } from "vitest";

import {
  reviewQueueItemsQueryKey,
  reviewQueuesQueryKey,
  scopedReviewQueueId,
} from "./reviewQueueState";

describe("scoped review queue selection", () => {
  const projectQueues = [{ id: "project-q1" }, { id: "project-q2" }];
  const datasetQueues = [{ id: "dataset-q1" }];

  it("permits only IDs present in the current project or dataset scope", () => {
    expect(scopedReviewQueueId("project-q2", projectQueues)).toBe("project-q2");
    expect(scopedReviewQueueId("project-q2", datasetQueues)).toBe("");
    expect(scopedReviewQueueId("dataset-q1", datasetQueues)).toBe("dataset-q1");
    expect(scopedReviewQueueId("missing", projectQueues)).toBe("");
  });

  it("fails closed while the new scope is loading or empty", () => {
    expect(scopedReviewQueueId("project-q1", undefined)).toBe("");
    expect(scopedReviewQueueId("project-q1", [])).toBe("");
    expect(scopedReviewQueueId("", projectQueues)).toBe("");
  });

  it("keeps project and dataset-version query caches distinct", () => {
    expect(reviewQueuesQueryKey("project-a", "project", "")).not.toEqual(
      reviewQueuesQueryKey("project-b", "project", ""),
    );
    expect(reviewQueuesQueryKey("project-a", "project", "")).not.toEqual(
      reviewQueuesQueryKey("project-a", "dataset_version", "dataset-1"),
    );
    expect(reviewQueueItemsQueryKey("", 1, "", "", "", "", "")).not.toEqual(
      reviewQueueItemsQueryKey("project-q1", 1, "", "", "", "", ""),
    );
  });
});
