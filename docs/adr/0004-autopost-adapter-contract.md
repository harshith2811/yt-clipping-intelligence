# ADR-0004: Dual-Mode Autopost Adapter with Idempotency & Dry-Run

## Status
Accepted

## Context
The user has an existing autopost automation that operates independently downstream. To ensure zero disruption:
- The autopost system must not be modified or rewritten.
- It must be treated as an external service of record.
- Handoff must prevent accidental public publishing during development and testing.
- Network retries must never result in duplicate video uploads or posts.

## Decision
We implement a **Dual-Mode Autopost Adapter** (`HandoffPublisher`):
1. **Modes of Operation:**
   - **Webhook/API Mode:** Posts a JSON handoff payload to a configured external REST endpoint with bearer token authentication.
   - **Watched-Folder Mode:** Atomically writes a `.json` manifest alongside the validated `.mp4` artifact into an output folder monitored by the autopost tool.
2. **Safety Controls:**
   - **Default Dry-Run Mode:** Enabled by default (`dry_run=True`), logging simulated handoff payloads and returning synthetic success receipts without executing live API calls or moving files.
   - **Idempotency Key:** Computed as a SHA-256 hash of `source_video_id + start_seconds + end_seconds + rights_id`. The publisher stores receipts and rejects duplicate submissions.
   - **Quality Assurance & Rights Gating:** Handoff is rejected if `rights_status != 'VERIFIED'` or `qa_status != 'PASSED'`.

## Consequences
- Safe local testing without accidental public publishing.
- High resilience against network failures and duplicate executions.
