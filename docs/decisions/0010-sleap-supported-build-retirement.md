# Decision 0010: retire active SLEAP support from supported builds

**Status:** Accepted on 2026-11-15

## Context

ReefVision's optional SLEAP-NN adapter targeted `sleap-nn==0.3.3`. The
authoritative source tag contains a GNU GPLv3 license file, while the same tag's
package metadata declares BSD-3-Clause. Those mutually inconsistent upstream
statements do not support a verified redistribution or supported-runtime
decision. The separately versioned `sleap-io==0.9.2` project carries a
BSD-3-Clause license and is used by ReefVision's neutral NWB codec.

## Decision

- Supported ReefVision builds do not register, run, train, advertise, install,
  or enable SLEAP-NN.
- SLP import/export is not a supported API or user-interface format.
- Existing database rows, source bundles, run metadata, canonical landmarks,
  tracks, annotations, and provenance with provider ID `sleap_nn` remain
  readable. Their provider descriptor is fail-closed with
  `availability_status=retired_license_audit`, no capabilities, and an
  actionable reason.
- Native ReefPose is the supported pose workflow.
- `sleap-io==0.9.2` may remain only in the optional interoperability extra for
  checksum-bound neutral NWB import/export. It does not make SLEAP-NN or SLP a
  supported path.
- Re-enabling active support requires an authoritative upstream license
  resolution, a fresh component/transitive/weight audit, owner approval, and
  new installed acceptance evidence.

## Consequences

Historical scientific evidence is preserved without loading retired executable
provider code. Users can continue with canonical ReefVision records or audited
neutral exports. Old SLP-only source artifacts are retained as source evidence
but require an external, independently licensed conversion before ReefVision
can import their pose payload.

This decision supersedes older roadmap, phase-plan, and report statements that
call SLEAP-NN or SLP a supported ReefVision capability.
