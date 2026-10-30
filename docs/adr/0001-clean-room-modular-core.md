# ADR-0001: Clean-Room Modular Core over OpenShorts or SupoClip Scaffold

## Status
Accepted

## Context
The project objective is to create a robust, tested master repository for automated YouTube video discovery, highlight selection, clip production, and handoff to an existing autopost automation. Two primary candidate scaffolds were evaluated:
1. `mutonby/openshorts`: Full-stack application with Next.js web UI, FastAPI, PostgreSQL, and Docker Compose.
2. `FujiwaraChoki/supoclip`: Rich video repurposing pipeline with virality scoring and social captions.

## Decision
We reject both projects as a foundation scaffold and choose a **clean-room modular Python master repository** (`src/yt_clipping/`):
- `supoclip` is licensed under **AGPL-3.0**. Copying its codebase would legally enforce AGPL-3.0 copyleft terms on the entire platform, conflicting with enterprise deployment and private downstream publishing systems.
- `openshorts` carries substantial front-end and full-stack containerization overhead that obscures core clipping intelligence and makes unit testing slow and tightly coupled.
- We adapt isolated, proven algorithmic patterns (Hook scoring from ClipMint, chunking and overlap suppression from AI-Youtube-Shorts-Generator, crash-resilient checkpoints from ClippyMe, and multi-speaker framing concepts from OpenShorts) under clean MIT / Apache-2.0 licensing, with complete attribution in `THIRD_PARTY_NOTICES.md`.

## Consequences
- The core platform remains lightweight, modular, easily installable via `uv` or `pip`, and 100% testable with standard `pytest`.
- Future integration of optional web dashboards or MCP servers can be added cleanly as modular layers on top of typed contracts.
