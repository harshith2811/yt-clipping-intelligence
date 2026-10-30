# ADR-0003: Separation of Public Views vs. Retention Curve Predictions

## Status
Accepted

## Context
A common misconception in automated video clipping is that public YouTube view counts or like counts indicate the most engaging moment inside a video. In reality:
- Public view counts reflect aggregate impressions across the entire video.
- Exact moment-by-moment audience retention (`audienceWatchRatio` vs `elapsedVideoTimeRatio`) is proprietary channel-level data exposed only through the authenticated YouTube Analytics API.
- For third-party creators whose channels are not authenticated, actual retention curves are completely inaccessible via compliant methods.

## Decision
The platform strictly separates **measured public velocity** from **predicted highlight moments**:
1. Discovery uses public metadata to calculate **View Velocity** ($\Delta \text{views} / \Delta \text{hours}$) normalized against channel baselines.
2. Highlight detection uses transcripts, acoustic energy, sentence structure, and narrative hooks to calculate an explainable **Predicted Highlight Score** (0-100).
3. The platform strictly prohibits fabricating or claiming that predicted peaks correspond to actual audience retention graphs.
4. When authorized channel-owner Analytics credentials are provided, genuine retention curves are ingested and compared against model predictions for calibration.

## Consequences
- Transparent, truthful scoring for operators and reviewers.
- Full compliance with Google/YouTube Developer Policies regarding metrics representation.
