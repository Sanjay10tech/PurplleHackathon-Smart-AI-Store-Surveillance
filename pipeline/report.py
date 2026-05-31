"""Markdown reports for full CCTV processing runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class VideoRunStats:
    video_name: str
    camera_name: str
    frames_processed: int
    events_generated: int
    status: str = "Processed"


@dataclass
class ProcessingRunReport:
    generated_at: datetime
    detector_mode: str
    correlation_id: str
    video_stats: list[VideoRunStats]
    ingest_summary: dict[str, int]
    total_visitors: int
    unmatched_videos: list[str]

    @property
    def total_videos_processed(self) -> int:
        return sum(1 for row in self.video_stats if row.status == "Processed")

    @property
    def total_frames_analyzed(self) -> int:
        return sum(row.frames_processed for row in self.video_stats)

    @property
    def total_events_generated(self) -> int:
        return sum(row.events_generated for row in self.video_stats)


def render_processing_report(report: ProcessingRunReport) -> str:
    lines = [
        "# Full CCTV Video Processing Report",
        "",
        f"**Generated:** {report.generated_at.astimezone(UTC).isoformat().replace('+00:00', 'Z')}",
        f"**Detector:** {report.detector_mode} (real YOLO — no mock)",
        f"**Pipeline run:** `{report.correlation_id}`",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
        f"| Videos processed | **{report.total_videos_processed}** |",
        f"| Total frames analyzed | **{report.total_frames_analyzed}** |",
        f"| Total events generated | **{report.total_events_generated}** |",
        f"| Total visitors detected | **{report.total_visitors}** |",
        "",
    ]

    if report.ingest_summary:
        lines.extend(
            [
                "### Ingest",
                "",
                "| Metric | Count |",
                "|--------|------:|",
            ]
        )
        for key in ("accepted", "rejected", "duplicate", "session_count"):
            if key in report.ingest_summary:
                lines.append(f"| {key} | {report.ingest_summary[key]} |")
        lines.append("")

    lines.extend(
        [
            "## Per-video results",
            "",
            "| Video | Frames Processed | Events Generated | Status |",
            "|-------|-----------------:|-----------------:|--------|",
        ]
    )
    for row in report.video_stats:
        lines.append(
            f"| {row.video_name} | {row.frames_processed} | {row.events_generated} | {row.status} |"
        )

    if report.unmatched_videos:
        lines.extend(["", "## Unmatched videos (no camera config)", ""])
        for name in report.unmatched_videos:
            lines.append(f"- `{name}`")

    lines.append("")
    return "\n".join(lines)


def write_processing_report(report: ProcessingRunReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_processing_report(report), encoding="utf-8")
    return path
