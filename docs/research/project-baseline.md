# Project Baseline & Workspace Findings

**Date:** 29 October 2026  
**Workspace Root:** `c:\Users\amara\OneDrive\Documents\yt`  
**Lead Orchestrator:** Antigravity Master Task

---

## 1. Executive Summary

This document establishes the verified baseline of the development workspace for the **YouTube Clipping Intelligence Platform**. It audits existing tools, runtimes, external dependencies, licensing boundaries, and downstream integration targets before initiating multi-agent architecture and vertical slice implementation.

---

## 2. Environment & Runtime Inventory

| Tool / Runtime | Location / Source | Verified Status | Operational Notes |
|---|---|---|---|
| **OS** | Windows 11 64-bit | Active | PowerShell host |
| **Python** | `.venv/Scripts/python.exe` (CPython 3.12.13) | Active | Provisioned via `uv 0.11.18` (from Comfy Desktop toolchain); full stdlib |
| **Package Manager** | `uv 0.11.18` | Active | Manages fast venv and dependency resolution |
| **Test Runner** | `pytest 9.2.0` | Active | Installed in `.venv`, verifies test suite |
| **Git CLI** | Visual Studio 2022 Community (`C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\TeamFoundation\Team Explorer\Git\cmd\git.exe`) | Active (v2.51.0) | Initialized repository on branch `main` |
| **FFmpeg CLI** | Subprocess / system pipeline | Documented | CLI binary not pre-installed in system PATH. Core renderer designed with robust FFmpeg command generation, stream probe validation, and synthetic test-fixture fallback |
| **External Autopost** | Remote / external system | Unobserved locally | Downstream autoposter is external; implemented via documented Webhook & Watched-Folder adapter with dry-run default |

---

## 3. Workspace Layout & Protection

The workspace has been protected with `.gitignore` to guarantee:
- Upstream cloned repositories (`research/upstream/`) remain read-only and isolated from master package imports and git history.
- Local virtual environments (`.venv/`) are excluded.
- Runtime media files (`*.mp4`, `data/`) and temporary render artifacts are excluded.
- API keys, credentials, and secrets are strictly excluded via `.env` rules.

---

## 4. Policy, Rights & Compliance Baseline

1. **Rights-First Architecture:**  
   Downloading or republishing YouTube videos without explicit owner authorization violates YouTube Developer Policies (Section III.E) and creator copyright. The master repository enforces a hard `RightsGate`: no video enters download, render, or publishing queues without a verified `RightsManifest` (owner authorization, licensed footage, or authorized local asset).
2. **Views vs. Retention Separation:**  
   Public YouTube Data API view counts represent aggregate external impressions, not timestamp-level engagement. Segment retention (`audienceWatchRatio`) requires authenticated YouTube Analytics API access from the channel owner. All model outputs without channel Analytics are strictly labeled as **Predicted Highlight Scores**; retention metrics are never fabricated.
3. **Autopost Protection:**  
   The downstream autopost automation is treated as an immutable external system. Handoff is conducted via stable JSON contracts with idempotency keys, delivery receipts, and default dry-run mode.

---

## 5. Next Steps

- Execute Phase 1: Comprehensive 40+ repository matrix, component map, license audit ledger, and scaffold recommendation.
- Execute Phase 2: System architecture, typed contracts, and Architectural Decision Records (ADRs).
- Execute Phase 3: Working vertical slice with automated verification.
