# ReefVision 1.6 review events

Review queue items now support comments, assignment and unassignment
events. The events are append-only and include a request UUID for retries.

The endpoints operate on the same queue identifiers produced by the
standalone QC service and the saved Workflow Builder.

Migration 0038 adds the event table. The feature is still under review.
