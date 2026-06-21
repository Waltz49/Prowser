#!/usr/bin/env python3
"""
Help dialog: downloading AI image-generation models (Hugging Face).
"""

from __future__ import annotations

import html
import sys
from dataclasses import dataclass
from typing import Dict, Set

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from theme.theme_service import get_active_theme
from thumbnails.thumbnail_constants import (
    BORDER_DEFAULT_HEX,
    BUTTON_BG_DEFAULT_HEX,
    COPY_SYMBOL,
    DIALOG_TEXT_COLOR_HEX,
    HEADING_COLOR_HEX,
)

_COLLAPSED_ARROW = "▶"
_EXPANDED_ARROW = "▼"

_HELP_BODY_PT = "14pt"
_HELP_H2_PT = "16pt"
_HELP_SECTION_PT = "15pt"
_HELP_CODE_PT = "12pt"
_HELP_COPY_ICON_PX = "18px"
_HELP_DIALOG_TITLE_PT = 20
_HELP_BUTTON_PT = 14
_HELP_COPY_FEEDBACK_PT = "13pt"


@dataclass(frozen=True)
class ModelDownloadEntry:
    section_id: str
    title: str
    repo_id: str
    usage: str
    gated: bool = False


@dataclass(frozen=True)
class LoraDownloadEntry:
    section_id: str
    title: str
    repo_id: str
    filename: str
    usage: str


MODEL_DOWNLOAD_ENTRIES: tuple[ModelDownloadEntry, ...] = (
    ModelDownloadEntry(
        section_id="flux_schnell_mflux",
        title="FLUX.1 Schnell MFLUX",
        repo_id="black-forest-labs/FLUX.1-schnell",
        usage="Create — FLUX.1 Schnell MFLUX",
        gated=True,
    ),
    ModelDownloadEntry(
        section_id="flux_dev",
        title="FLUX.1 Dev",
        repo_id="black-forest-labs/FLUX.1-dev",
        usage="Create — FLUX.1 Dev",
        gated=True,
    ),
    ModelDownloadEntry(
        section_id="flux_fill",
        title="FLUX.1 Fill",
        repo_id="black-forest-labs/FLUX.1-Fill-dev",
        usage="Expand and Infill",
        gated=True,
    ),
    ModelDownloadEntry(
        section_id="flux2_klein_4b",
        title="FLUX.2 Klein 4B",
        repo_id="black-forest-labs/FLUX.2-klein-4B",
        usage="Create and Edit — FLUX.2 Klein 4B",
        gated=True,
    ),
    ModelDownloadEntry(
        section_id="flux2_klein_9b",
        title="FLUX.2 Klein 9B",
        repo_id="black-forest-labs/FLUX.2-klein-9B",
        usage="Create and Edit — FLUX.2 Klein 9B",
        gated=True,
    ),
    ModelDownloadEntry(
        section_id="flux2_klein_9b_kv",
        title="FLUX.2 Klein 9B KV",
        repo_id="black-forest-labs/FLUX.2-klein-9b-kv",
        usage="Create and Edit — FLUX.2 Klein 9B KV",
        gated=True,
    ),
    ModelDownloadEntry(
        section_id="sana_sprint",
        title="SANA Sprint 0.6B 1024px",
        repo_id="Efficient-Large-Model/Sana_Sprint_0.6B_1024px_diffusers",
        usage="Create — SANA Sprint 0.6B 1024px (diffusers)",
        gated=False,
    ),
    ModelDownloadEntry(
        section_id="anything_furry",
        title="Anything Furry",
        repo_id="stablediffusionapi/anythingfurry",
        usage="Create — Anything Furry (SD 1.5 anime/furry; bundled VAE; use with LoRAs)",
        gated=False,
    ),
    ModelDownloadEntry(
        section_id="realistic_vision_v4",
        title="Realistic Vision V4.0 noVAE",
        repo_id="SG161222/Realistic_Vision_V4.0_noVAE",
        usage="Create — Realistic Vision V4.0 (SD 1.5 photoreal; pair with SD VAE below)",
        gated=False,
    ),
    ModelDownloadEntry(
        section_id="sd15_vae",
        title="SD 1.5 VAE (ft-mse)",
        repo_id="stabilityai/sd-vae-ft-mse",
        usage="Required VAE for Realistic Vision V4.0 noVAE",
        gated=False,
    ),
)

LORA_DOWNLOAD_ENTRIES: tuple[LoraDownloadEntry, ...] = (
    LoraDownloadEntry(
        section_id="sd15_lora_anime",
        title="Anime character LoRA (SD 1.5)",
        repo_id="Shion1124/anime-character-lora_v1.5",
        filename="adapter_model.safetensors",
        usage="Create — Anything Furry — anime style LoRA",
    ),
    LoraDownloadEntry(
        section_id="sd15_lora_furry",
        title="Furry LoRA (SD 1.5)",
        repo_id="hank87/furrylora",
        filename="furry_lora.safetensors",
        usage="Create — Anything Furry — furry / anthro LoRA",
    ),
)


def _hf_cli_path_snippet() -> str:
    """Shell snippet: HF points at Prowser venv hf or hf on PATH (no Homebrew required)."""
    return (
        'HF="./venv_image_browser/bin/hf"\n'
        'if [ ! -x "$HF" ]; then\n'
        '  HF="$(command -v hf 2>/dev/null || true)"\n'
        "fi\n"
        'if [ -z "$HF" ] || [ ! -x "$HF" ]; then\n'
        '  echo "hf not found. Run the install script below (pip install -U huggingface_hub)." >&2\n'
        "  exit 1\n"
        "fi\n"
    )


def _pip_python_snippet() -> str:
    """Shell snippet: PYTHON for pip install into Prowser venv or system python3."""
    return (
        'PYTHON="./venv_image_browser/bin/python"\n'
        '[ -x "$PYTHON" ] || PYTHON="python3"\n'
    )


def _download_script_for_repo(repo_id: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -e\n"
        "\n"
        f'REPO_ID="{repo_id}"\n'
        "\n"
        f"{_hf_cli_path_snippet()}\n"
        "\n"
        '"$HF" download "$REPO_ID"\n'
    )


def _lora_cache_dir(repo_id: str) -> str:
    return f"$HOME/.cache/image_browser/mflux_loras/{repo_id.replace('/', '__')}"


def _download_script_for_lora(repo_id: str, filename: str) -> str:
    local_dir = _lora_cache_dir(repo_id)
    return (
        "#!/usr/bin/env bash\n"
        "set -e\n"
        "\n"
        f'REPO_ID="{repo_id}"\n'
        f'FILENAME="{filename}"\n'
        f'LOCAL_DIR="{local_dir}"\n'
        "\n"
        f"{_hf_cli_path_snippet()}\n"
        "\n"
        'mkdir -p "$LOCAL_DIR"\n'
        '"$HF" download "$REPO_ID" "$FILENAME" --local-dir "$LOCAL_DIR"\n'
    )


def _hf_cli_install_script() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -e\n"
        "\n"
        f"{_pip_python_snippet()}\n"
        "\n"
        '"$PYTHON" -m pip install -U huggingface_hub\n'
    )


def _hf_login_script() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -e\n"
        "\n"
        f"{_hf_cli_path_snippet()}\n"
        "\n"
        '"$HF" auth login\n'
    )


def _scripts_by_id() -> Dict[str, str]:
    scripts = {
        entry.section_id: _download_script_for_repo(entry.repo_id)
        for entry in MODEL_DOWNLOAD_ENTRIES
    }
    for entry in LORA_DOWNLOAD_ENTRIES:
        scripts[entry.section_id] = _download_script_for_lora(
            entry.repo_id, entry.filename
        )
    scripts["hf_cli_install"] = _hf_cli_install_script()
    scripts["hf_login"] = _hf_login_script()
    return scripts


def _toggle_header(
    section_id: str,
    title: str,
    expanded: Set[str],
    heading_hex: str,
    *,
    suffix_html: str = "",
) -> str:
    is_open = section_id in expanded
    arrow = _EXPANDED_ARROW if is_open else _COLLAPSED_ARROW
    sid = html.escape(section_id, quote=True)
    return (
        f'<div style="margin: 10px 0 4px 0;">'
        f'<a href="toggle://{sid}" '
        f'style="color: {heading_hex}; text-decoration: none; font-size: {_HELP_SECTION_PT}; '
        f'font-weight: bold;">{html.escape(arrow)} {html.escape(title)}</a>'
        f"{suffix_html}"
        f"</div>"
    )


def build_downloading_models_html(expanded: Set[str]) -> str:
    """Build help HTML; section bodies shown only when section_id is in expanded."""
    th = get_active_theme()
    text_hex = getattr(th, "text_color_hex", DIALOG_TEXT_COLOR_HEX)
    heading_hex = getattr(th, "heading_color_hex", HEADING_COLOR_HEX)
    border_hex = getattr(th, "default_border_color_hex", BORDER_DEFAULT_HEX)
    code_bg = getattr(th, "button_bg_default_hex", BUTTON_BG_DEFAULT_HEX)
    accent_hex = getattr(th, "accent_color_hex", heading_hex)
    muted_hex = getattr(th, "information_action_icon_muted_hex", text_hex)
    hover_hex = getattr(th, "button_border_hover_hex", accent_hex)

    def p(body: str) -> str:
        return (
            f'<p style="margin: 0 0 10px 0; color: {text_hex}; '
            f'font-size: {_HELP_BODY_PT}; line-height: 1.45;">{body}</p>'
        )

    parts: list[str] = [
        (
            f'<div style="color: {text_hex}; font-family: -apple-system, '
            f'"Helvetica Neue", Helvetica, Arial, sans-serif; font-size: {_HELP_BODY_PT}; '
            f'line-height: 1.45;">'
        ),
        p(
            "AI IS COMPLETELY OPTIONAL. Prowser is an image browser, but some AI features "
            "are available if you want to use them."
        ),
        p(
            'If <a href="https://lmstudio.ai/">LM Studio</a> is installed and the server '
            "is running, you can use it to generate EXIF captions."
        ),
        p(
            "For the Create menu features, Prowser will attempt to download model "
            "weights automatically the first time you use a Create, Edit, Expand, or "
            "Infill feature. Nothing will be downloaded without your permission. "
            "Downloads are large (often several gigabytes) and are stored under your "
            "Hugging Face cache, typically "
            "<code>~/.cache/huggingface</code>."
        ),
        p(
            "If a download fails or stalls, you may need to install the model manually. "
            "To see detailed error messages, run Prowser from a terminal using one of these "
            "approaches:"
        ),
        (
            '<ul style="margin: 0 0 12px 20px; padding: 0; color: '
            f'{text_hex}; font-size: {_HELP_BODY_PT}; line-height: 1.45;">'
            "<li>Copy the <b>source folder</b> from the DMG, run "
            "<code>./setup.sh</code>, then <code>./run.sh</code> from Terminal.</li>"
            "<li>Run the installed app from Terminal: "
            "<code>/Applications/Prowser.app/Contents/MacOS/Prowser</code></li>"
            "<li>Download the model manually (see below).</li>"
            "</ul>"
        ),
        (
            f'<h2 style="color: {heading_hex}; font-size: {_HELP_H2_PT}; margin: 18px 0 8px 0;">'
            "Download models</h2>"
        ),
        p(
            "For 'gated' modles, you will need to set a variable called 'HF_TOKEN' in your environment. "
            "  <code>EXPORT HF_TOKEN=<your-token></code>"
            "where <your-token> is your Hugging Face token. You can find your token in your Hugging Face account settings."
        ),
        p(
            "Expand a model to see its repository and download script. Save the script "
            "(for example as <code>download-model.sh</code>), "
            "run <code>chmod +x download-model.sh</code>, then "
            "<code>./download-model.sh</code> from Terminal — or paste the commands into "
            "zsh (the first line is only needed when saving as a <code>.sh</code> file). "
            "Scripts use <code>./venv_image_browser/bin/hf</code> when present, otherwise "
            "<code>hf</code> on your PATH (no Homebrew required). "
            "Click <span style=\"font-family: monospace;\">"
            f"{html.escape(COPY_SYMBOL)}</span> to copy a script to the clipboard."
        ),
    ]

    for entry in MODEL_DOWNLOAD_ENTRIES:
        model_url = f"https://huggingface.co/{html.escape(entry.repo_id, quote=True)}"
        gated_note = (
            ' <span style="color: #c9a227;">(gated — accept license on Hugging Face first)</span>'
            if entry.gated
            else ""
        )
        parts.append(
            _toggle_header(
                entry.section_id,
                entry.title,
                expanded,
                heading_hex,
                suffix_html=gated_note,
            )
        )
        if entry.section_id not in expanded:
            continue
        parts.append(
            p(
                f"<b>Used for:</b> {html.escape(entry.usage)}<br>"
                f'<b>Repository:</b> <a href="{model_url}">'
                f"{html.escape(entry.repo_id)}</a>"
            )
        )
        parts.append(
            _script_block(
                entry.section_id,
                _download_script_for_repo(entry.repo_id),
                code_bg,
                border_hex,
                muted_hex,
                hover_hex,
                show_copy=True,
            )
        )

    parts.append(
        (
            f'<h2 style="color: {heading_hex}; font-size: {_HELP_H2_PT}; margin: 22px 0 8px 0;">'
            "Download LoRAs</h2>"
        )
    )
    parts.append(
        p(
            "LoRA weights are small adapter files (typically tens to hundreds of MB). "
            "Prowser downloads them on first use when you pick a LoRA in Create, or you "
            "can install them manually with the scripts below. SD 1.5 LoRAs are stored under "
            "<code>~/.cache/image_browser/mflux_loras/</code>."
        )
    )
    for entry in LORA_DOWNLOAD_ENTRIES:
        model_url = f"https://huggingface.co/{html.escape(entry.repo_id, quote=True)}"
        parts.append(
            _toggle_header(
                entry.section_id,
                entry.title,
                expanded,
                heading_hex,
            )
        )
        if entry.section_id not in expanded:
            continue
        parts.append(
            p(
                f"<b>Used for:</b> {html.escape(entry.usage)}<br>"
                f"<b>File:</b> <code>{html.escape(entry.filename)}</code><br>"
                f'<b>Repository:</b> <a href="{model_url}">'
                f"{html.escape(entry.repo_id)}</a>"
            )
        )
        parts.append(
            _script_block(
                entry.section_id,
                _download_script_for_lora(entry.repo_id, entry.filename),
                code_bg,
                border_hex,
                muted_hex,
                hover_hex,
                show_copy=True,
            )
        )

    parts.extend(
        [
            (
                f'<h2 style="color: {heading_hex}; font-size: {_HELP_H2_PT}; margin: 22px 0 8px 0;">'
                "Hugging Face</h2>"
            ),
            p(
                "Manual downloads use the <code>hf</code> command-line tool (replaces the "
                "legacy <code>huggingface-cli</code>). Install it once, then log in if you "
                "use gated FLUX models."
            ),
            _toggle_header(
                "hf_cli_install",
                "Install hf CLI",
                expanded,
                heading_hex,
            ),
        ]
    )
    if "hf_cli_install" in expanded:
        parts.append(
            p(
                "Install into the same Python environment you use for Prowser "
                "(for example the project virtual environment):"
            )
        )
        parts.append(
            _script_block(
                "hf_cli_install",
                _hf_cli_install_script(),
                code_bg,
                border_hex,
                muted_hex,
                hover_hex,
                show_copy=True,
            )
        )
        parts.append(
            p(
                "Verify (from the Prowser source folder): "
                "<code>./venv_image_browser/bin/hf --help</code>"
            )
        )

    parts.extend(
        [
            _toggle_header(
                "hf_account",
                "Account and gated models",
                expanded,
                heading_hex,
            ),
        ]
    )
    if "hf_account" in expanded:
        parts.append(
            p(
                "Several FLUX models require a free Hugging Face account and accepting the "
                "model license on the model page before download will succeed:"
            )
        )
        parts.append(
            (
                '<ol style="margin: 0 0 12px 22px; padding: 0; color: '
                f'{text_hex}; font-size: {_HELP_BODY_PT}; line-height: 1.45;">'
                '<li>Create an account at <a href="https://huggingface.co/join">'
                "huggingface.co</a> (if you do not have one).</li>"
                "<li>Open the model page for the repo you need (links are under each model above).</li>"
                "<li>Sign in, read the license, and click <b>Agree and access repository</b> "
                "when prompted.</li>"
                "<li>Log in from the CLI using the bash script below.</li>"
                "</ol>"
            )
        )
        parts.append(
            _script_block(
                "hf_login",
                _hf_login_script(),
                code_bg,
                border_hex,
                muted_hex,
                hover_hex,
                show_copy=True,
            )
        )
        parts.append(
            p(
                "After login, re-run the download script or try generation again in Prowser."
            )
        )

    parts.append("</div>")
    return "".join(parts)


def _script_block(
    block_id: str,
    script_text: str,
    code_bg: str,
    border_hex: str,
    muted_hex: str,
    hover_hex: str,
    *,
    show_copy: bool,
) -> str:
    escaped_script = html.escape(script_text)
    copy_cell = ""
    if show_copy:
        copy_cell = (
            f'<td style="border: none; vertical-align: top; padding: 4px 0 0 6px;">'
            f'<a href="copy://{html.escape(block_id, quote=True)}" '
            f'style="display: block; color: {muted_hex}; text-decoration: none; '
            f'font-size: {_HELP_COPY_ICON_PX}; line-height: 24px; border: 1px solid {border_hex}; '
            f"border-radius: 6px; padding: 0 6px; text-align: center;\" "
            f'title="Copy to clipboard">{html.escape(COPY_SYMBOL)}</a>'
            f"</td>"
        )
    return (
        f'<table cellpadding="0" cellspacing="0" style="width: 100%; margin: 0 0 12px 0;">'
        f"<tr>"
        f'<td style="border: 1px solid {border_hex}; border-radius: 6px; '
        f"background: {code_bg}; padding: 8px 10px; width: 100%;\">"
        f'<pre style="margin: 0; white-space: pre-wrap; word-break: break-word; '
        f'font-family: Menlo, Monaco, \"Courier New\", monospace; font-size: {_HELP_CODE_PT}; '
        f'color: {DIALOG_TEXT_COLOR_HEX};">{escaped_script}</pre>'
        f"</td>"
        f"{copy_cell}"
        f"</tr></table>"
    )


class DownloadingAIModelsHelpDialog(QDialog):
    """HTML help for downloading image-generation models."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Downloading AI Models")
        self.setModal(True)
        self._expanded: Set[str] = set()
        self._scripts = _scripts_by_id()
        self._content_browser: QTextBrowser | None = None
        self._setup_ui()
        self._refresh_html()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        title = QLabel(self.windowTitle())
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(_HELP_DIALOG_TITLE_PT)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        self._content_browser = QTextBrowser(self)
        browser = self._content_browser
        browser.setReadOnly(True)
        browser.setOpenExternalLinks(True)
        browser.setOpenLinks(False)
        browser.anchorClicked.connect(self._on_anchor_clicked)
        browser.setStyleSheet(
            f"""
            QTextBrowser {{
                background-color: {BUTTON_BG_DEFAULT_HEX};
                color: {DIALOG_TEXT_COLOR_HEX};
                border: 1px solid {BORDER_DEFAULT_HEX};
                border-radius: 4px;
                padding: 12px;
                font-size: {_HELP_BODY_PT};
            }}
            """
        )
        layout.addWidget(browser, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch()
        close_button = QPushButton("Close")
        close_button.setDefault(True)
        btn_font = QFont()
        btn_font.setPointSize(_HELP_BUTTON_PT)
        close_button.setFont(btn_font)
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.setMinimumSize(640, 480)
        self.resize(920, 720)

    def _refresh_html(self) -> None:
        if self._content_browser is None:
            return
        self._content_browser.setHtml(build_downloading_models_html(self._expanded))

    def _on_anchor_clicked(self, url: QUrl) -> None:
        scheme = url.scheme()
        if scheme in ("http", "https"):
            QDesktopServices.openUrl(url)
            return

        target = url.host()
        raw = url.toString()
        if not target and raw.startswith("toggle://"):
            target = raw.removeprefix("toggle://")
        elif not target and raw.startswith("copy://"):
            target = raw.removeprefix("copy://")

        if scheme == "toggle" and target:
            if target in self._expanded:
                self._expanded.discard(target)
            else:
                self._expanded.add(target)
            self._refresh_html()
            return

        if scheme == "copy" and target:
            text = self._scripts.get(target, "")
            if text:
                from copy_feedback import copy_text_to_clipboard

                copy_text_to_clipboard(
                    text,
                    anchor=self._content_browser,
                    font_size=_HELP_COPY_FEEDBACK_PT,
                )
            return

    def showEvent(self, event) -> None:
        super().showEvent(event)
        for widget in self.findChildren(QPushButton):
            if widget.text() == "Close":
                widget.setFocus()
                break


def show_downloading_models_help(parent=None) -> None:
    dialog = DownloadingAIModelsHelpDialog(parent)
    dialog.exec()


def main() -> None:
    app = QApplication(sys.argv)
    dialog = DownloadingAIModelsHelpDialog()
    dialog.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
