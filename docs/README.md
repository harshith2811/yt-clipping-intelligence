# YouTube Clipping Intelligence Platform — Documentation Portal

Welcome to the definitive documentation index for the **YouTube Clipping Intelligence Platform**. This portal provides structured access to all architectural guides, specifications, technical references, and release audits.

---

## 📚 Master Documentation Map

```text
docs/
├── README.md                      # Documentation Hub & Navigation Portal (This File)
├── ARCHITECTURE.md                # System Topology, Pipeline Data Flow & Component Design
├── PODCAST_ENGINE.md              # 9:8 Stacked Split-Screen, Diarization & Shot Detection
├── mcp.md                         # Model Context Protocol (MCP) JSON-RPC 2.0 Specification
├── CLI_REFERENCE.md               # Complete Command-Line Interface Manual & Flags
├── MODULE_REFERENCE.md            # Exhaustive Python Module, Class & API Directory
├── VIRALITY_AND_ATTRIBUTION.md    # Virality Multiplier, Velocity Scoring & Rights Governance
├── ACTIVE_SPEAKER_AND_CAPTIONS.md # Face Tracking, Kinematic Trajectory & Subtitle Presets
├── RELEASE_READINESS_REPORT.md    # Production Audit, VRAM Verification & Hardware Matrix
├── COMPREHENSIVE_TEST_REPORT.md   # Exhaustive Test Matrix (381 Passed, 100% Pass Rate)
├── adr/                           # Architectural Decision Records (ADRs)
│   ├── 0001-clean-room-modular-core.md
│   ├── 0002-hard-rights-gate-enforcement.md
│   ├── 0003-views-vs-retention-separation.md
│   └── 0004-autopost-adapter-contract.md
└── research/                      # Upstream Competitive Benchmarks & Research Dossiers
    ├── antigravity_master_yt_clipping_prompt.md
    ├── license-and-provenance.md
    ├── progress.md
    ├── project-baseline.md
    ├── repository-matrix.md
    └── yt_clipping_master_repo_research.md
```

---

## 🔍 Core Specifications & Guides

### 1. [System Architecture](ARCHITECTURE.md)
Detailed breakdown of the entire platform topology, from zero-quota discovery to final NVENC-accelerated FFmpeg compositing:
- High-level topology and Mermaid diagrams.
- 10-stage deterministic data lifecycle.
- Zero-VRAM graceful fallback cascade.
- Crash resilience and durable SQLite WAL job state machine.

### 2. [Podcast Short Maker Engine](PODCAST_ENGINE.md)
Specialized guide for multi-speaker interview and podcast processing:
- Mathematical 9:8 stacked split-screen layout (host top, guest bottom, center divider).
- Dual-engine speaker diarization (`PyannoteDiarizerAdapter` and 0MB VRAM `AcousticEnergyDiarizer`).
- Automated shot detection and director close-up switching.
- Center-divider anchored animated subtitles (`MarginV = height // 2`).

### 3. [Model Context Protocol (MCP) Server](mcp.md)
Complete specification for LLM agent integration conforming to the `2024-11-05` standard:
- 7 discrete tool schemas: discovery, rights, transcription, highlight detection, dead-air pruning, vertical rendering, and job status.
- Line-delimited JSON-RPC 2.0 stdio transport guarantees.
- Setup instructions for Claude Desktop, Cursor, Antigravity, and custom LLM workflows.

### 4. [CLI Operator Reference](CLI_REFERENCE.md)
Exhaustive guide to all command-line tools:
- Master `yt-clip` subcommands (`process`, `discover`, `podcast`, `rights`, `queue`, `mcp`).
- All runtime flags, default values, and environment variable overrides.
- Concrete real-world terminal invocation recipes.

### 5. [Module & API Reference](MODULE_REFERENCE.md)
Exhaustive Python API directory documenting every package, class, contract, and entrypoint in `src/yt_clipping/`.

### 6. [Virality & Attribution Intelligence](VIRALITY_AND_ATTRIBUTION.md)
In-depth analysis of our outlier virality multiplier, hourly velocity equations, audience resonance gates ($LVR \ge 1.2\%$, $CVR \ge 0.03\%$), and creator compliance ledger.

### 7. [Active Speaker & Kinetic Captions](ACTIVE_SPEAKER_AND_CAPTIONS.md)
Deep dive into YuNet ONNX face detection, AutoFlip kinematic trajectory optimization (SciPy banded solver), and word-synced ASS subtitle animation presets (`hormozi`, `beast`, `neon`, `minimal`).

---

## 🛡️ Production & Audit Reports

- **[Release Readiness Report](RELEASE_READINESS_REPORT.md):** Verification of $\le 4\text{GB}$ VRAM constraints, CPU fallbacks, zero-quota ingestion, and architectural boundaries.
- **[Comprehensive Test Report](COMPREHENSIVE_TEST_REPORT.md):** Full test suite execution telemetry covering all 381 passing tests, stress scenarios, and adversarial fault-injection tests.

---

## 🏛️ Architectural Decision Records (ADRs)

- **[ADR 0001: Clean-Room Modular Core](adr/0001-clean-room-modular-core.md)**
- **[ADR 0002: Hard Rights-Gate Enforcement](adr/0002-hard-rights-gate-enforcement.md)**
- **[ADR 0003: Views vs Retention Separation](adr/0003-views-vs-retention-separation.md)**
- **[ADR 0004: Autopost Adapter Contract](adr/0004-autopost-adapter-contract.md)**
