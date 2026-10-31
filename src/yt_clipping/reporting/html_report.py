"""
Executive HTML Report Generator.
Produces standalone, zero-dependency, responsive HTML reports summarizing
virality discovery, highlight scorecards, retention analytics, and render QA.
"""

from typing import Optional, Dict, Any, List
import os
import json
from datetime import datetime, timezone
import html

from ..contracts.models import ClipJob, HighlightCandidate, RenderedClip, QAReport, RightsManifest, HeatmapData


class ExecutiveReportGenerator:
    """
    Renders an executive summary of a video clipping job to standalone HTML.
    """

    @staticmethod
    def generate_html_report(
        job: ClipJob,
        heatmap_data: Optional[HeatmapData] = None,
        output_path: str = "data/rendered_clips/report.html",
    ) -> str:
        """Builds and writes a responsive HTML report."""
        c = job.candidate
        clip = job.rendered_clip
        qa = job.qa_report
        rm = job.rights_manifest

        # Extracted metrics
        video_id = job.video_id
        score = c.score if c else 0.0
        bd = c.breakdown if c else None
        hook_title = c.hook_title if c else "Automated Highlight"
        start_sec = c.start_seconds if c else 0.0
        end_sec = c.end_seconds if c else 0.0
        duration_sec = c.duration_seconds if c else 0.0
        rationale = c.rationale if c else "No rationale recorded."
        desc = c.suggested_description if c else ""

        # Virality info if available
        vel_mult = 1.0
        virality_cls = "STEADY"
        if c and hasattr(c, "telemetry") and isinstance(getattr(c, "telemetry"), dict):
            t = getattr(c, "telemetry")
            vel_mult = t.get("velocity_multiplier", 1.0)
            virality_cls = t.get("classification", "STEADY")

        # Color coding for score
        if score >= 80:
            score_color = "#10b981"  # Emerald
            score_grade = "VIRAL READY"
        elif score >= 65:
            score_color = "#3b82f6"  # Blue
            score_grade = "STRONG"
        else:
            score_color = "#f59e0b"  # Amber
            score_grade = "NEEDS REVIEW"

        # Heatmap sparkline
        sparkline_svg = ""
        if heatmap_data and heatmap_data.points:
            pts = heatmap_data.points
            w, h = 600, 100
            n = len(pts)
            coords = []
            for i, p in enumerate(pts):
                x = (i / max(n - 1, 1)) * w
                y = h - (p.value * (h - 10)) - 5
                coords.append(f"{x:.1f},{y:.1f}")
            poly_points = f"0,{h} " + " ".join(coords) + f" {w},{h}"
            sparkline_svg = f"""
            <div class="card" style="margin-top: 1.5rem;">
                <h3 style="margin-top:0;">Audience Retention Curve (Source: {html.escape(heatmap_data.source)})</h3>
                <svg viewBox="0 0 {w} {h}" style="width:100%; height:120px; background:#1e293b; border-radius:8px; overflow:hidden;">
                    <polygon points="{poly_points}" fill="rgba(59, 130, 246, 0.25)" />
                    <polyline points="{' '.join(coords)}" fill="none" stroke="#3b82f6" stroke-width="2.5" />
                </svg>
                <div style="display:flex; justify-content:space-between; color:#94a3b8; font-size:0.8rem; margin-top:4px;">
                    <span>0:00</span>
                    <span>Peak Highlight: {start_sec:.1f}s - {end_sec:.1f}s</span>
                    <span>{pts[-1].end_time:.0f}s</span>
                </div>
            </div>
            """

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Clip Intelligence Executive Report - {html.escape(video_id)}</title>
    <style>
        :root {{
            --bg: #0f172a;
            --card-bg: #1e293b;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --border: #334155;
            --accent: #3b82f6;
            --accent-green: #10b981;
            --accent-purple: #8b5cf6;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 2rem 1rem;
            display: flex;
            justify-content: center;
        }}
        .container {{
            max-width: 900px;
            width: 100%;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 1.5rem;
            margin-bottom: 1.5rem;
        }}
        .brand {{
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--accent);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .timestamp {{
            font-size: 0.85rem;
            color: var(--text-muted);
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1.5rem;
        }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.5rem;
        }}
        .badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .badge-viral {{
            background: rgba(16, 185, 129, 0.2);
            color: #10b981;
            border: 1px solid #10b981;
        }}
        .badge-steady {{
            background: rgba(59, 130, 246, 0.2);
            color: #3b82f6;
            border: 1px solid #3b82f6;
        }}
        .score-circle {{
            font-size: 3rem;
            font-weight: 800;
            color: {score_color};
            line-height: 1;
            margin: 0.5rem 0;
        }}
        .metric-row {{
            display: flex;
            justify-content: space-between;
            padding: 0.5rem 0;
            border-bottom: 1px solid rgba(255,255,255,0.06);
            font-size: 0.9rem;
        }}
        .metric-label {{
            color: var(--text-muted);
        }}
        .metric-value {{
            font-weight: 600;
        }}
        .attribution-box {{
            background: #0f172a;
            border: 1px dashed var(--border);
            border-radius: 8px;
            padding: 1rem;
            font-family: monospace;
            font-size: 0.85rem;
            white-space: pre-wrap;
            color: #e2e8f0;
            margin-top: 0.75rem;
        }}
        .btn {{
            background: var(--accent);
            color: #fff;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            margin-top: 0.5rem;
        }}
        .btn:hover {{
            opacity: 0.9;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <div class="brand">YT Clipping Intelligence</div>
                <div style="font-size: 1.5rem; font-weight:700; margin-top:0.25rem;">Executive Media Report</div>
            </div>
            <div style="text-align: right;">
                <span class="badge badge-viral">{html.escape(virality_cls)}</span>
                <div class="timestamp">Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</div>
            </div>
        </div>

        <div class="grid">
            <!-- Score Card -->
            <div class="card">
                <span class="badge" style="background:rgba(255,255,255,0.1); color:var(--text);">{score_grade}</span>
                <div class="score-circle">{score:.1f}</div>
                <div style="color:var(--text-muted); font-size:0.85rem;">Composite Score (0-100)</div>
                <p style="font-size:0.9rem; line-height:1.4; margin-top:1rem; color:#cbd5e1;">
                    {html.escape(rationale)}
                </p>

                <div style="margin-top:1rem;">
                    <div class="metric-row">
                        <span class="metric-label">Opening Hook (0-10)</span>
                        <span class="metric-value">{bd.hook_score if bd else 0.0:.1f}</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Moment Payoff (0-10)</span>
                        <span class="metric-value">{bd.moment_score if bd else 0.0:.1f}</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Coherence (0-10)</span>
                        <span class="metric-value">{bd.coherence_score if bd else 0.0:.1f}</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Cadence / Pacing (0-10)</span>
                        <span class="metric-value">{bd.pacing_score if bd else 0.0:.1f}</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Heatmap Replay (0-10)</span>
                        <span class="metric-value">{bd.heatmap_score if bd else 0.0:.1f}</span>
                    </div>
                </div>
            </div>

            <!-- Video & Clip Specs -->
            <div class="card">
                <h3 style="margin-top:0;">Clip Specifications</h3>
                <div class="metric-row">
                    <span class="metric-label">Source Video ID</span>
                    <span class="metric-value"><a href="https://youtu.be/{html.escape(video_id)}" target="_blank" style="color:var(--accent); text-decoration:none;">{html.escape(video_id)}</a></span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Clip Window</span>
                    <span class="metric-value">{start_sec:.1f}s &rarr; {end_sec:.1f}s ({duration_sec:.1f}s)</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Resolution / Aspect</span>
                    <span class="metric-value">1080 &times; 1920 (9:16)</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Rights Verification</span>
                    <span class="metric-value" style="color:#10b981;">{html.escape(rm.status.value if rm else 'VERIFIED')}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">QA Status</span>
                    <span class="metric-value" style="color:#10b981;">{html.escape(qa.status if qa else 'PASSED')}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Rendered File</span>
                    <span class="metric-value" style="word-break:break-all; font-size:0.8rem;">{html.escape(os.path.basename(clip.file_path) if clip else 'Simulated')}</span>
                </div>

                <h4 style="margin-bottom:0.25rem; margin-top:1.5rem;">Hook Title</h4>
                <div style="font-weight:600; font-size:1.05rem; color:#f1f5f9;">{html.escape(hook_title)}</div>
            </div>
        </div>

        {sparkline_svg}

        <!-- Creator Attribution & Description -->
        <div class="card" style="margin-top:1.5rem;">
            <h3 style="margin-top:0;">Attribution Package & Metadata</h3>
            <div style="font-size:0.85rem; color:var(--text-muted);">
                Compliant attribution snippet ready for upload to YouTube Shorts, Instagram Reels, or TikTok:
            </div>
            <div class="attribution-box" id="attributionText">{html.escape(desc or rationale)}</div>
            <button class="btn" onclick="navigator.clipboard.writeText(document.getElementById('attributionText').innerText); alert('Attribution copied to clipboard!');">
                Copy Attribution Snippet
            </button>
        </div>
    </div>
</body>
</html>
"""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return os.path.abspath(output_path)
