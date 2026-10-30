# ADR-0002: Hard RightsGate Enforcement Before Media Pipelines

## Status
Accepted

## Context
Automated video clipping often risks infringing third-party copyrights or violating platform terms of service. Section III.E of the YouTube API Services Developer Policies explicitly prohibits downloading, importing, caching, or storing copies of YouTube audiovisual content without prior written permission. Reposting content without authorization creates severe legal liability and account termination risks.

## Decision
We implement a mandatory **`RightsGate`** component in the pipeline. Every video candidate must have a verified `RightsManifest` prior to entering:
1. Media retrieval / downloading via `AssetProvider`.
2. Audio/video decoding and vertical rendering via `Renderer`.
3. Downstream publishing via `HandoffPublisher`.

If rights verification is absent or status is `PENDING` or `REVOKED`:
- The asset's public discovery metadata is preserved.
- A human-review task is logged in the operational database.
- Downstream processing halts with an explicit `RightsPolicyViolationError`.
- No media is downloaded or stored.

Allowed verification bases include:
- `OWNED`: The operator owns the channel or content.
- `EXPLICIT_PERMISSION`: Written creator authorization with verifiable proof.
- `CREATIVE_COMMONS`: Verified CC BY 3.0 / 4.0 license on source video.
- `OPERATOR_ASSET`: Local file supplied directly by the operator.

## Consequences
- Protects the operator from copyright infringement and API policy strikes.
- Ensures the platform operates strictly within compliant boundaries.
