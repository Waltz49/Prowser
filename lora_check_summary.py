#!/usr/bin/env python3
"""Standalone viewer for a Check LoRAs report summary.

Reads a check_loras_last_run.txt report (written by Check LoRAs) and shows the
Results summary with collapsible sections — without launching Prowser or writing
the source report file.

Usage:
  python lora_check_summary.py
  python lora_check_summary.py -f /path/to/check_loras_last_run.txt
"""

from __future__ import annotations

import argparse
import ast
import html
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

DEFAULT_REPORT = Path(__file__).resolve().parent / "check_loras_last_run.txt"
OPTION_SYMBOL = "⌥"

_SECTION_RE = re.compile(r"^=== (.+) ===\s*$")
_CHANGE_RE = re.compile(
    r"^  \[([^\]]+)\] (?:(.+?) → (.+)|(.+))\s*$"
)
_MORE_CHANGES_RE = re.compile(r"^  … and (\d+) more changes\s*$")
_ELAPSED_RE = re.compile(r"^Total elapsed:\s*(.+)\s*$")
_GPU_RE = re.compile(r"^GPU renders:\s*(\d+)/(\d+)\s*$")
_BY_MODEL_HEADER_RE = re.compile(
    r"^  (.+?) \(([^)]+)\):\s*(\d+) enabled\s*$"
)
_MODEL_SUPPORT_RE = re.compile(r"^  ([^:]+):\s*(\[.*\])\s*(?:\(changed\))?\s*$")

_COLLAPSE_TOOLTIP = (
    "Click to expand or collapse this section.\n"
    f"{OPTION_SYMBOL}+click to expand or collapse all sections."
)


@dataclass
class Change:
    kind: str
    lora_label: str
    model_label: str = ""
    lora_id: str = ""
    model_key: str = ""


@dataclass
class SummarySection:
    key: str
    title: str
    lines: List[str]


@dataclass
class SummaryDoc:
    intro_lines: List[str]
    sections: List[SummarySection]
    footer_lines: List[str]


@dataclass
class ParsedReport:
    path: Path
    timestamp: str = ""
    profile_report: str = ""
    workspace_copy: str = ""
    cancelled: bool = False
    gpu_probes_done: int = 0
    probes_total: int = 0
    history_reused: int = 0
    loras_with_pass: int = 0
    newly_enabled: int = 0
    failed_probes: int = 0
    skipped_registered: int = 0
    model_support: Dict[str, List[str]] = field(default_factory=dict)
    by_model_enabled: Dict[str, Tuple[str, List[str]]] = field(default_factory=dict)
    changes: List[Change] = field(default_factory=list)
    truncated_changes: int = 0
    elapsed_text: str = ""
    raw_summary_lines: List[str] = field(default_factory=list)


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes")


def _parse_int_after_colon(line: str) -> Optional[int]:
    if ":" not in line:
        return None
    try:
        return int(line.split(":", 1)[1].strip())
    except ValueError:
        return None


def parse_report(path: Path) -> ParsedReport:
    """Parse a Check LoRAs report. Never writes the file."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    report = ParsedReport(path=path)

    if lines and lines[0].startswith("Check LoRAs report"):
        report.timestamp = lines[0].split("—", 1)[-1].strip()
    for line in lines[:5]:
        if line.startswith("Profile report:"):
            report.profile_report = line.split(":", 1)[1].strip()
        elif line.startswith("Workspace copy:"):
            report.workspace_copy = line.split(":", 1)[1].strip()

    section: Optional[str] = None
    i = 0
    while i < len(lines):
        line = lines[i]
        sec = _SECTION_RE.match(line)
        if sec:
            section = sec.group(1)
            i += 1
            continue

        if section == "Summary":
            if line.strip():
                report.raw_summary_lines.append(line)
            m = _GPU_RE.match(line)
            if m:
                report.gpu_probes_done = int(m.group(1))
                report.probes_total = int(m.group(2))
            elif line.startswith("Cancelled:"):
                report.cancelled = _parse_bool(line.split(":", 1)[1])
            elif line.startswith("History reused:"):
                v = _parse_int_after_colon(line)
                if v is not None:
                    report.history_reused = v
            elif line.startswith("LoRAs with pass:"):
                v = _parse_int_after_colon(line)
                if v is not None:
                    report.loras_with_pass = v
            elif line.startswith("Newly enabled:"):
                v = _parse_int_after_colon(line)
                if v is not None:
                    report.newly_enabled = v
            elif line.startswith("Failed probes:"):
                v = _parse_int_after_colon(line)
                if v is not None:
                    report.failed_probes = v
            elif line.startswith("Skipped registered:"):
                v = _parse_int_after_colon(line)
                if v is not None:
                    report.skipped_registered = v

        elif section == "model_support in result (before save)":
            m = _MODEL_SUPPORT_RE.match(line)
            if m:
                lid = m.group(1).strip()
                try:
                    models = ast.literal_eval(m.group(2))
                except (SyntaxError, ValueError):
                    models = []
                if isinstance(models, list):
                    report.model_support[lid] = [str(x) for x in models]

        elif section == "by_model enabled_ids in result (before save)":
            m = _BY_MODEL_HEADER_RE.match(line)
            if m:
                label, key, _count = m.group(1), m.group(2), int(m.group(3))
                enabled: List[str] = []
                j = i + 1
                while j < len(lines):
                    item = lines[j]
                    if item.startswith("    • "):
                        enabled.append(item[6:].strip())
                        j += 1
                    elif item.startswith("    … and "):
                        j += 1
                        break
                    else:
                        break
                report.by_model_enabled[key] = (label, enabled)
                i = j
                continue

        elif section == "Changes":
            more = _MORE_CHANGES_RE.match(line)
            if more:
                report.truncated_changes = int(more.group(1))
            else:
                m = _CHANGE_RE.match(line)
                if m:
                    kind = m.group(1)
                    if m.group(2) is not None:
                        model_label = m.group(2).strip()
                        lora_label = m.group(3).strip()
                    else:
                        model_label = ""
                        lora_label = (m.group(4) or "").strip()
                    report.changes.append(
                        Change(
                            kind=kind,
                            lora_label=lora_label,
                            model_label=model_label,
                            lora_id=lora_label,
                            model_key=model_label,
                        )
                    )

        elapsed = _ELAPSED_RE.match(line)
        if elapsed:
            report.elapsed_text = elapsed.group(1).strip()

        i += 1

    return report


def _changes_of(changes: List[Change], kind: str) -> List[Change]:
    return [c for c in changes if c.kind == kind]


def _format_change_lines(
    items: List[Change], *, with_model: bool = True
) -> List[str]:
    lines: List[str] = []
    for c in items:
        if with_model and c.model_label:
            lines.append(f"  • {c.model_label} → {c.lora_label}")
        else:
            lines.append(f"  • {c.lora_label}")
    return lines


def build_summary_doc(report: ParsedReport) -> SummaryDoc:
    """Build intro / collapsible sections / footer for the summary view."""
    intro: List[str] = [
        (
            "Check LoRAs cancelled (partial results saved)."
            if report.cancelled
            else "Check LoRAs finished."
        ),
        "",
        f"Reconstructed from report: {report.path}",
    ]
    if report.timestamp:
        intro.append(f"Report timestamp: {report.timestamp}")

    newly_enabled = _changes_of(report.changes, "newly_enabled")
    newly_supported = _changes_of(report.changes, "newly_supported")
    failed = _changes_of(report.changes, "failed")
    lost = _changes_of(report.changes, "lost_support")
    hidden = _changes_of(report.changes, "skipped_hidden")
    not_disk = _changes_of(report.changes, "skipped_not_on_disk")
    downloads_registered = _changes_of(report.changes, "downloads_registered")
    downloads_deduped = _changes_of(report.changes, "downloads_deduped")
    downloads_failed = _changes_of(report.changes, "downloads_failed")

    newly_enabled_count = report.newly_enabled or len(newly_enabled)
    failed_count = report.failed_probes or len(failed)

    summary_lines = [
        f"  GPU renders: {report.gpu_probes_done}/{report.probes_total}",
        f"  LoRAs with at least one pass: {report.loras_with_pass}",
        f"  Newly compatible pairs listed: {len(newly_supported)}",
        f"  Newly enabled in Settings: {newly_enabled_count}",
        f"  Failed probes: {failed_count}",
    ]
    if not_disk:
        summary_lines.append(f"  Skipped (not on disk): {len(not_disk)}")
    if hidden:
        summary_lines.append(f"  Skipped (hidden — not enabled): {len(hidden)}")
    if report.skipped_registered:
        summary_lines.append(
            f"  Skipped (already registered): {report.skipped_registered}"
        )
    if report.history_reused:
        summary_lines.append(
            f"  Skipped unchanged renders: {report.history_reused}"
        )
    if report.truncated_changes:
        summary_lines.append(
            f"  Changes listed in report: "
            f"{len(report.changes)} (+{report.truncated_changes} truncated)"
        )

    enabled_keys = {(c.lora_id, c.model_key) for c in newly_enabled}
    hidden_keys = {(c.lora_id, c.model_key) for c in hidden}
    compat_only = [
        c
        for c in newly_supported
        if (c.lora_id, c.model_key) not in enabled_keys
        and (c.lora_id, c.model_key) not in hidden_keys
    ]

    sections: List[SummarySection] = [
        SummarySection("summary", "Summary", summary_lines),
    ]

    def add_change_section(
        key: str,
        title: str,
        items: List[Change],
        *,
        with_model: bool = True,
        report_total: Optional[int] = None,
    ) -> None:
        if not items and not (report_total and report_total > 0):
            return
        if report_total is not None and report_total > len(items):
            heading = f"{title} ({len(items)} listed of {report_total})"
        else:
            heading = f"{title} ({len(items)})"
        sections.append(
            SummarySection(key, heading, _format_change_lines(items, with_model=with_model))
        )

    add_change_section(
        "newly_enabled",
        "Newly enabled",
        newly_enabled,
        report_total=newly_enabled_count,
    )
    add_change_section(
        "downloads_registered", "Downloads registered", downloads_registered
    )
    add_change_section(
        "compat_only", "Newly compatible (not newly enabled)", compat_only
    )
    add_change_section(
        "failed",
        "Failed probes",
        failed,
        report_total=failed_count,
    )
    add_change_section("lost", "Lost prior compatibility", lost)
    add_change_section("hidden", "Passed but hidden (left disabled)", hidden)
    add_change_section(
        "downloads_deduped",
        "Downloads duplicates removed",
        downloads_deduped,
        with_model=False,
    )
    add_change_section(
        "downloads_failed",
        "Downloads with no passing model",
        downloads_failed,
        with_model=False,
    )
    add_change_section(
        "not_disk",
        "Skipped — weights not on disk",
        not_disk,
        with_model=False,
    )

    footer: List[str] = []
    if report.truncated_changes:
        footer.extend(
            [
                "Note: the report file truncates its Changes list at 500 entries "
                f"({report.truncated_changes} more were not stored). "
                "Section lists above show only what is present in the file; "
                "Summary totals come from the report header.",
                "",
            ]
        )
    footer.extend(
        [
            "Each on-disk LoRA is probed against every installed base model. Passing "
            "pairs are recorded and enabled in Settings → LoRA (unless previously Hidden).",
            "Weights are discovered under ~/.cache/image_browser/mflux_loras, "
            "~/.cache/mflux_loras (recursive), and top-level ~/Downloads "
            "*.safetensors. Duplicate files (same md5) are probed once. "
            "Unchanged files reuse prior probe history.",
            "Re-run after downloading new LoRA weights. Use Hide in Settings to "
            "keep a LoRA out of the menus.",
        ]
    )
    if report.elapsed_text:
        footer.extend(["", f"Total elapsed: {report.elapsed_text}"])

    return SummaryDoc(intro_lines=intro, sections=sections, footer_lines=footer)


def format_summary_text(
    doc: SummaryDoc, *, expanded: Optional[Dict[str, bool]] = None
) -> str:
    """Plain-text summary. When expanded is None, include all section bodies."""
    lines = list(doc.intro_lines)
    for section in doc.sections:
        lines.append("")
        is_open = True if expanded is None else expanded.get(section.key, True)
        indicator = "▼" if is_open else "▶"
        lines.append(f"{indicator} {section.title}")
        if is_open:
            lines.extend(section.lines)
    if doc.footer_lines:
        lines.append("")
        lines.extend(doc.footer_lines)
    return "\n".join(lines)


def _palette_hexes() -> Tuple[str, str]:
    """Return (text_color, heading_color) from the active Qt palette."""
    from PySide6.QtGui import QPalette

    app = QApplication.instance()
    if app is None:
        return "#000000", "#000000"
    pal = app.palette()
    text = pal.color(QPalette.ColorRole.Text).name()
    return text, text


def _collapsible_header_html(
    section_key: str, title: str, expanded: bool, *, heading_color: str
) -> str:
    indicator = "▼" if expanded else "▶"
    margin = "10px" if expanded else "4px"
    safe_title = html.escape(title)
    return (
        f'<div style="font-weight: bold; font-size: 12pt; margin: 10px 0 {margin} 0;">'
        f'<a href="infocollapse://{section_key}" '
        f'style="color: {heading_color}; text-decoration: none; cursor: pointer;" '
        f'title="{html.escape(_COLLAPSE_TOOLTIP)}">'
        f"{indicator} {safe_title}</a></div>"
    )


def format_summary_html(doc: SummaryDoc, expanded: Dict[str, bool]) -> str:
    text_color, heading_color = _palette_hexes()
    parts: List[str] = [
        f'<div style="font-family: Helvetica, Arial, sans-serif; '
        f'font-size: 12px; line-height: 1.35; color: {text_color};">'
    ]
    for line in doc.intro_lines:
        parts.append(f"<div>{html.escape(line) if line else '&nbsp;'}</div>")

    for section in doc.sections:
        is_open = expanded.get(section.key, True)
        parts.append(
            _collapsible_header_html(
                section.key, section.title, is_open, heading_color=heading_color
            )
        )
        if is_open:
            body = "<br>".join(html.escape(line) for line in section.lines) or "&nbsp;"
            parts.append(
                f'<div style="margin: 0 0 8px 8px; white-space: pre-wrap; '
                f'color: {text_color};">{body}</div>'
            )

    if doc.footer_lines:
        parts.append(f'<div style="margin-top: 12px; color: {text_color};">')
        for line in doc.footer_lines:
            parts.append(f"<div>{html.escape(line) if line else '&nbsp;'}</div>")
        parts.append("</div>")
    parts.append("</div>")
    return "".join(parts)


class LoraCheckSummaryDialog(QDialog):
    def __init__(self, report: ParsedReport, parent=None) -> None:
        super().__init__(parent)
        self._report = report
        self._doc = build_summary_doc(report)
        self._expanded: Dict[str, bool] = {
            section.key: True for section in self._doc.sections
        }

        self.setWindowTitle("Check LoRAs — Results")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(720, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        intro = QLabel(
            "Changes from this Check LoRAs run (from report file). "
            f"Click a section header to expand/collapse; {OPTION_SYMBOL}+click "
            "toggles all sections."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._body = QTextBrowser()
        self._body.setReadOnly(True)
        self._body.setOpenLinks(False)
        self._body.setOpenExternalLinks(False)
        self._body.anchorClicked.connect(self._on_anchor_clicked)
        text_color, heading_color = _palette_hexes()
        self._body.document().setDefaultStyleSheet(
            f"body {{ color: {text_color}; }} "
            f"a {{ color: {heading_color}; text-decoration: none; }}"
        )
        layout.addWidget(self._body, 1)

        buttons = QDialogButtonBox()
        save_btn = QPushButton("Save…")
        save_btn.clicked.connect(self._save_summary)
        buttons.addButton(save_btn, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._rebuild_html()

    def _rebuild_html(self) -> None:
        scroll = self._body.verticalScrollBar().value()
        self._body.setHtml(format_summary_html(self._doc, self._expanded))
        self._body.verticalScrollBar().setValue(scroll)

    def _on_anchor_clicked(self, url: QUrl) -> None:
        if url.scheme() != "infocollapse":
            if url.scheme() in ("http", "https", "file"):
                QDesktopServices.openUrl(url)
            return
        section_key = url.host() or ""
        if not section_key or section_key not in self._expanded:
            return
        option_held = bool(
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier
        )
        new_state = not self._expanded[section_key]
        if option_held:
            for key in self._expanded:
                self._expanded[key] = new_state
        else:
            self._expanded[section_key] = new_state
        self._rebuild_html()

    def _default_save_path(self) -> Path:
        stamp = self._report.timestamp.replace(":", "").replace("T", "_") or "summary"
        return Path.home() / "Downloads" / f"lora_check_summary_{stamp}.txt"

    def _save_summary(self) -> None:
        suggested = str(self._default_save_path())
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save Check LoRAs summary",
            suggested,
            "Text files (*.txt);;All files (*)",
        )
        if not path_str:
            return
        path = Path(path_str)
        # Save full content (all sections expanded), independent of UI collapse state.
        text = format_summary_text(self._doc, expanded=None)
        try:
            path.write_text(text + "\n", encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        QMessageBox.information(self, "Saved", f"Summary saved to:\n{path}")


def show_summary_dialog(report: ParsedReport) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    dlg = LoraCheckSummaryDialog(report)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    # Terminal-launched apps on macOS often start behind the frontmost app.
    if sys.platform == "darwin":
        try:
            from AppKit import NSApp

            NSApp.activateIgnoringOtherApps_(True)
        except Exception:
            pass
    return dlg.exec()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="View a Check LoRAs summary from a saved report file."
    )
    parser.add_argument(
        "-f",
        "--file",
        type=Path,
        default=DEFAULT_REPORT,
        help=f"Path to check_loras_last_run.txt (default: {DEFAULT_REPORT})",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        dest="print_only",
        help="Print summary text to stdout instead of opening the dialog.",
    )
    args = parser.parse_args(argv)

    path = args.file.expanduser().resolve()
    if not path.is_file():
        print(f"Report file not found: {path}", file=sys.stderr)
        return 1

    # Source report is read-only; Save writes a separate summary file.
    report = parse_report(path)
    doc = build_summary_doc(report)
    if args.print_only:
        print(format_summary_text(doc, expanded=None))
        return 0

    return 0 if show_summary_dialog(report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
