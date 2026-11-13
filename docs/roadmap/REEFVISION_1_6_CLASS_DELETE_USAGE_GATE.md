# ReefVision 1.6 — class deletion requires verified usage

## Previously unsafe UI affordance
The Delete unused button interpreted a missing usage response as `can_delete=true` while the usage query was disabled by default. An irreversible action could therefore be offered before the scientist inspected references. The backend protects referential integrity, but the interface presented misleading permission.

## Implemented behavior
The button starts disabled. Opening Usage fetches current project/class-scoped evidence. Deletion is enabled only after a successful response reports `can_delete === true`, no request is currently fetching, and the evidence remains visible. Failed, pending, hidden, and stale-while-refetching usage gates all fail closed. The existing explicit confirmation and server-side deletion constraints are retained. A summary with zero itemized entries no longer falsely claims the class unused when its total references are nonzero.

## Regression and scientific boundary
React Testing Library tests cover unresolved usage, a successful empty result and real deletion request, hiding and reopening Usage, a referenced class, HTTP 503, and a previously eligible cached result being refreshed into a referenced result. This local class-management guard does not change scientific annotations, immutable dataset/model class maps, or the previously implemented executable saved `qc_review_queue` Workflow Builder node and reviewer approval gates. No new graph node or migration is justified for a destructive UI confirmation.

Full exact-commit frontend/backend CI, migration compatibility, representative scientific QC, and installed Windows MSI/GUI validation remain required before release.