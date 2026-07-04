#!/usr/bin/env python3
"""
Resize selected images (Pillow): replace in place or uniquely suffixed copy
(screen_size_copy naming), optional DPI, optional preserve timestamps, EXIF UserComment on output.
"""

from __future__ import annotations

import os
import tempfile
from typing import List, Optional, Sequence, Tuple

from PIL import Image

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from config import get_config
from exif.exif_utils import (
    format_supports_exif,
    get_exif_bytes_from_pil,
    get_usercomment_from_path,
    restore_usercomment_to_file,
)
from screen_size_copy import generate_unique_filename
from utils import (
    file_string,
    wrap_progress_dialog_label_elision,
    get_button_style,
    is_inside_photos_library,
    show_styled_critical,
    show_styled_warning,
)


def _pil_resampling_choices() -> Sequence[Tuple[str, int]]:
    """User-visible resampling names and Pillow resampling filter ints."""
    r = getattr(Image, "Resampling", None)
    if r is not None:
        out: List[Tuple[str, int]] = [
            ("Lanczos", r.LANCZOS),
            ("Bicubic", r.BICUBIC),
            ("Bilinear", r.BILINEAR),
            ("Nearest", r.NEAREST),
        ]
        if hasattr(r, "BOX"):
            out.insert(3, ("Box", r.BOX))
        if hasattr(r, "HAMMING"):
            out.append(("Hamming", r.HAMMING))
        return tuple(out)
    return (
        ("Lanczos", Image.LANCZOS),
        ("Bicubic", Image.BICUBIC),
        ("Bilinear", Image.BILINEAR),
        ("Nearest", Image.NEAREST),
    )


def _extension_save_format(ext_lower: str) -> Optional[str]:
    m = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".gif": "GIF",
        ".bmp": "BMP",
        ".webp": "WEBP",
        ".tiff": "TIFF",
        ".tif": "TIFF",
    }
    return m.get(ext_lower)


def _format_supports_embed_dpi(ext_lower: str) -> bool:
    return ext_lower in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}


MAX_RESIZE_DIMENSION = 6000
PERCENT_SCALE_MIN = 20
PERCENT_SCALE_MAX = 200
PERCENT_SCALE_DEFAULT = 100


def _read_dpi_from_pil(img: Image.Image) -> Optional[int]:
    d = img.info.get("dpi") if img.info else None
    if not d:
        return None
    try:
        if isinstance(d, tuple) and len(d) >= 2:
            return int(round((float(d[0]) + float(d[1])) / 2.0))
        if isinstance(d, tuple) and len(d) == 1:
            return int(round(float(d[0])))
        return int(round(float(d)))
    except (TypeError, ValueError):
        return None


def _compute_target_size(
    orig_w: int,
    orig_h: int,
    dialog_w: int,
    dialog_h: int,
    preserve_aspect: bool,
    anchor_is_width: bool,
) -> Tuple[int, int]:
    if orig_w <= 0 or orig_h <= 0:
        return max(1, dialog_w), max(1, dialog_h)
    if not preserve_aspect:
        return max(1, dialog_w), max(1, dialog_h)
    if anchor_is_width:
        tw = max(1, dialog_w)
        th = max(1, int(round(orig_h * tw / float(orig_w))))
        return tw, th
    th = max(1, dialog_h)
    tw = max(1, int(round(orig_w * th / float(orig_h))))
    return tw, th


def resize_image_file(
    image_path: str,
    target_w: int,
    target_h: int,
    preserve_aspect: bool,
    anchor_is_width: bool,
    resample: int,
    dpi: Optional[int],
    embed_dpi: bool,
    ignore_exif: bool,
    delete_original: bool,
    preserve_dates: bool,
    scale_percent: Optional[int] = None,
) -> Tuple[bool, Optional[str], bool, Optional[str]]:
    """
    Load, resize, and save. If delete_original: replace image_path in place.
    Else: write to generate_unique_filename(image_path) (same convention as Create screen size copy).

    Returns (success, error_message, wrote_file, output_path_or_none).
    """
    if not os.path.exists(image_path):
        return False, "File does not exist", False, None
    if is_inside_photos_library(image_path):
        return False, "Cannot resize files inside a Photos Library", False, None

    ext = os.path.splitext(image_path)[1].lower()
    save_format = _extension_save_format(ext)
    if not save_format:
        return False, "Unsupported file type for resize", False, None

    usercomment_bytes = get_usercomment_from_path(image_path)

    orig_atime: Optional[float] = None
    orig_mtime: Optional[float] = None
    if preserve_dates:
        try:
            st0 = os.stat(image_path)
            orig_atime, orig_mtime = st0.st_atime, st0.st_mtime
        except OSError:
            pass

    try:
        from pil_image_io import open_pil_with_exif_correction

        img = open_pil_with_exif_correction(image_path, ignore_exif=ignore_exif, cr2_half_size=False)
        if img is None:
            return False, "Could not open image", False, None

        resized = None
        try:
            ow, oh = img.size
            if scale_percent is not None:
                pct = max(PERCENT_SCALE_MIN, min(PERCENT_SCALE_MAX, int(scale_percent)))
                tw = max(1, int(round(ow * pct / 100.0)))
                th = max(1, int(round(oh * pct / 100.0)))
                tw = min(tw, MAX_RESIZE_DIMENSION)
                th = min(th, MAX_RESIZE_DIMENSION)
            else:
                tw, th = _compute_target_size(
                    ow, oh, target_w, target_h, preserve_aspect, anchor_is_width
                )
            if tw == ow and th == oh:
                return True, None, False, None

            exif_bytes = get_exif_bytes_from_pil(img)

            transparency_supported_formats = {"PNG", "GIF", "WEBP", "TIFF"}
            preserve_transparency = save_format in transparency_supported_formats

            if preserve_transparency:
                if img.mode == "P":
                    if "transparency" in img.info:
                        img = img.convert("RGBA")
                    else:
                        img = img.convert("RGB")
                elif img.mode in ("RGBA", "LA"):
                    pass
                elif img.mode != "RGB":
                    img = img.convert("RGB")
            else:
                if img.mode in ("RGBA", "LA", "P"):
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    background.paste(
                        img,
                        mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None,
                    )
                    img = background
                elif img.mode != "RGB":
                    img = img.convert("RGB")

            resized = img.resize((tw, th), resample)

            save_kwargs = {}
            if save_format == "JPEG":
                save_kwargs["quality"] = 95
                save_kwargs["optimize"] = True
            elif save_format == "PNG":
                save_kwargs["compress_level"] = 6
            elif save_format == "WEBP":
                if resized.mode in ("RGBA", "LA"):
                    save_kwargs["lossless"] = True
                else:
                    save_kwargs["quality"] = 95
                    save_kwargs["method"] = 6

            if exif_bytes and format_supports_exif(save_format):
                save_kwargs["exif"] = exif_bytes

            if embed_dpi and dpi is not None and dpi > 0 and _format_supports_embed_dpi(ext):
                save_kwargs["dpi"] = (dpi, dpi)

            icc = resized.info.get("icc_profile") if resized.info else None
            if icc:
                save_kwargs["icc_profile"] = icc

            out_dir = os.path.dirname(image_path) or "."
            final_path = image_path if delete_original else generate_unique_filename(image_path)
            fd, tmp_path = tempfile.mkstemp(prefix=".resize_", suffix=ext, dir=out_dir)
            os.close(fd)
            try:
                resized.save(tmp_path, format=save_format, **save_kwargs)
                os.replace(tmp_path, final_path)
            except Exception:
                try:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            if usercomment_bytes:
                if not restore_usercomment_to_file(final_path, usercomment_bytes):
                    print(f"Warning: could not restore EXIF UserComment on {final_path}")

            if preserve_dates and orig_atime is not None and orig_mtime is not None:
                try:
                    os.utime(final_path, (orig_atime, orig_mtime))
                except OSError as e:
                    print(f"Warning: could not preserve timestamps for {final_path}: {e}")

            return True, None, True, final_path
        finally:
            try:
                img.close()
            except Exception:
                pass
            if resized is not None:
                try:
                    resized.close()
                except Exception:
                    pass
    except PermissionError as e:
        return False, f"Permission denied: {e}", False, None
    except OSError as e:
        return False, f"Failed to save: {e}", False, None
    except Exception as e:
        return False, str(e), False, None


class ResizeImagesDialog(QDialog):
    """Resize dialog: dimensions, aspect lock, DPI (when supported), resampling."""

    def __init__(self, parent, files: List[str], ref_width: int, ref_height: int):
        super().__init__(parent)
        self.files = files
        self.ref_width = max(1, ref_width)
        self.ref_height = max(1, ref_height)
        self._updating = False

        cfg = get_config()
        settings = cfg.load_settings()
        self._saved_preserve = bool(settings.get("resize_preserve_aspect", True))
        self._saved_resample_label = settings.get("resize_resample_method", "Lanczos")
        self._saved_embed_dpi = bool(settings.get("resize_embed_dpi", True))
        self._saved_delete_original = bool(settings.get("resize_delete_original", False))
        self._saved_preserve_dates = bool(settings.get("resize_preserve_dates", True))
        self._anchor_is_width = bool(settings.get("resize_anchor_is_width", True))

        self.result_width = self.ref_width
        self.result_height = self.ref_height
        self.preserve_aspect = self._saved_preserve
        self.resample_filter = _pil_resampling_choices()[0][1]
        self.embed_dpi = self._saved_embed_dpi
        self.dpi_value: Optional[int] = None
        self.delete_original = self._saved_delete_original
        self.preserve_dates = self._saved_preserve_dates
        self.use_percent_scale = False
        self.percent_scale = PERCENT_SCALE_DEFAULT

        self._setup_ui(settings)

    @staticmethod
    def _spin_box_char_width(spin: QSpinBox, chars: int = 5) -> int:
        fm = spin.fontMetrics()
        return fm.horizontalAdvance("0" * chars) + 28

    def _percent_mode_allowed(self) -> bool:
        return self.ref_width <= MAX_RESIZE_DIMENSION and self.ref_height <= MAX_RESIZE_DIMENSION

    def _max_percent_for_reference(self) -> int:
        if self.ref_width < 1 or self.ref_height < 1:
            return PERCENT_SCALE_MAX
        max_w = int(MAX_RESIZE_DIMENSION * 100 / self.ref_width)
        max_h = int(MAX_RESIZE_DIMENSION * 100 / self.ref_height)
        return max(PERCENT_SCALE_MIN, min(PERCENT_SCALE_MAX, max_w, max_h))

    def _dimensions_from_percent(self, percent: int) -> Tuple[int, int]:
        pct = max(PERCENT_SCALE_MIN, min(self._max_percent_for_reference(), int(percent)))
        w = max(1, int(round(self.ref_width * pct / 100.0)))
        h = max(1, int(round(self.ref_height * pct / 100.0)))
        w = min(w, MAX_RESIZE_DIMENSION)
        h = min(h, MAX_RESIZE_DIMENSION)
        return w, h

    def _update_final_size_label(self) -> None:
        if self.percent_radio.isChecked():
            pct = int(self.percent_slider.value())
            w, h = self._dimensions_from_percent(pct)
            self.final_size_label.setText(f"Final size: {w} × {h} pixels ({pct}%)")
        else:
            w = int(self.width_spin.value())
            h = int(self.height_spin.value())
            self.final_size_label.setText(f"Final size: {w} × {h} pixels")

    def _set_mode_controls_enabled(self) -> None:
        dims_mode = self.dims_radio.isChecked()
        self.width_spin.setEnabled(dims_mode)
        self.height_spin.setEnabled(dims_mode)
        self.preserve_cb.setEnabled(dims_mode)
        for btn in self._dim_helper_buttons:
            btn.setEnabled(dims_mode)
        percent_enabled = (not dims_mode) and self._percent_mode_allowed()
        self.percent_slider.setEnabled(percent_enabled)
        self.percent_value_label.setEnabled(percent_enabled)
        self._update_final_size_label()

    def _on_mode_changed(self) -> None:
        if self.percent_radio.isChecked():
            max_pct = self._max_percent_for_reference()
            self.percent_slider.setRange(PERCENT_SCALE_MIN, max_pct)
            self._updating = True
            try:
                self.percent_slider.setValue(min(PERCENT_SCALE_DEFAULT, max_pct))
            finally:
                self._updating = False
            self._on_percent_changed(self.percent_slider.value())
        self._set_mode_controls_enabled()

    def _on_percent_changed(self, value: int) -> None:
        if self._updating:
            return
        pct = int(value)
        self.percent_value_label.setText(f"{pct}%")
        self._update_final_size_label()

    def _setup_ui(self, settings: dict) -> None:
        self.setWindowTitle("Resize Images" if len(self.files) > 1 else "Resize Image")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        layout.addWidget(
            QLabel(f"Current size: {self.ref_width} × {self.ref_height} pixels")
        )

        if len(self.files) > 1:
            layout.addWidget(
                QLabel(f"{len(self.files)} {file_string(len(self.files))} will be resized.")
            )

        first_ext = os.path.splitext(self.files[0])[1].lower()
        self._dpi_supported = _format_supports_embed_dpi(first_ext)

        self._dim_helper_buttons: List[QPushButton] = []

        self.mode_group = QButtonGroup(self)
        self.dims_radio = QRadioButton("Dimensions")
        self.percent_radio = QRadioButton("Percent")
        self.mode_group.addButton(self.dims_radio, 0)
        self.mode_group.addButton(self.percent_radio, 1)
        layout.addWidget(self.dims_radio)

        dims_section = QVBoxLayout()
        dims_section.setSpacing(6)
        dims_section.setContentsMargins(20, 0, 0, 0)

        dims_row = QHBoxLayout()
        dims_row.addWidget(QLabel("Width:"))
        spin_hi = self._dim_spin_max()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, spin_hi)
        self.width_spin.setValue(self.ref_width)
        self.width_spin.setFixedWidth(self._spin_box_char_width(self.width_spin))
        dims_row.addWidget(self.width_spin)
        dims_row.addSpacing(12)
        dims_row.addWidget(QLabel("Height:"))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, spin_hi)
        self.height_spin.setValue(self.ref_height)
        self.height_spin.setFixedWidth(self._spin_box_char_width(self.height_spin))
        dims_row.addWidget(self.height_spin)
        dims_row.addStretch(1)
        dims_section.addLayout(dims_row)

        try:
            from imagegen_plugins.image_gen_form_layout import (
                create_image_gen_dim_helper_icon_button,
            )
            from imagegen_plugins.imagegen_control_tooltips import apply_dim_helper_tooltips

            dim_btn_layout = QHBoxLayout()
            dim_btn_layout.setContentsMargins(0, 0, 0, 0)
            dim_btn_layout.setSpacing(4)
            dim_btn_layout.addStretch(1)
            square_btn = create_image_gen_dim_helper_icon_button(
                "dim_square_icon.png",
                hover_icon_name="dim_square_icon_hover.png",
                parent=self,
            )
            square_btn.clicked.connect(self._on_square_dims)
            reverse_btn = create_image_gen_dim_helper_icon_button(
                "dim_reverse_icon.png",
                hover_icon_name="dim_reverse_icon_hover.png",
                parent=self,
            )
            reverse_btn.clicked.connect(self._on_reverse_dims)
            screen_btn = create_image_gen_dim_helper_icon_button(
                "dim_screen_icon.png",
                hover_icon_name="dim_screen_icon_hover.png",
                parent=self,
            )
            screen_btn.clicked.connect(self._on_screen_size_dims)
            apply_dim_helper_tooltips(
                screen_btn=screen_btn,
                square_btn=square_btn,
                reverse_btn=reverse_btn,
            )
            for btn in (square_btn, reverse_btn, screen_btn):
                dim_btn_layout.addWidget(btn)
                self._dim_helper_buttons.append(btn)
            dims_section.addLayout(dim_btn_layout)
        except ImportError:
            pass

        layout.addLayout(dims_section)

        layout.addWidget(self.percent_radio)
        percent_section = QVBoxLayout()
        percent_section.setSpacing(6)
        percent_section.setContentsMargins(20, 0, 0, 0)
        percent_row = QHBoxLayout()
        max_pct = self._max_percent_for_reference()
        self.percent_slider = QSlider(Qt.Orientation.Horizontal)
        self.percent_slider.setRange(PERCENT_SCALE_MIN, max_pct)
        self.percent_slider.setValue(min(PERCENT_SCALE_DEFAULT, max_pct))
        self.percent_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.percent_slider.setTickInterval(20)
        self.percent_value_label = QLabel(f"{self.percent_slider.value()}%")
        self.percent_value_label.setMinimumWidth(42)
        percent_row.addWidget(self.percent_slider, 1)
        percent_row.addWidget(self.percent_value_label)
        percent_section.addLayout(percent_row)
        layout.addLayout(percent_section)

        if not self._percent_mode_allowed():
            self.percent_radio.setEnabled(False)
            self.percent_radio.setToolTip(
                f"Percent scaling is unavailable when either side exceeds "
                f"{MAX_RESIZE_DIMENSION} pixels."
            )

        self.final_size_label = QLabel()
        layout.addWidget(self.final_size_label)

        self.dims_radio.setChecked(True)
        if not self._percent_mode_allowed():
            self.dims_radio.setChecked(True)

        self.preserve_cb = QCheckBox("Preserve aspect ratio")
        self.preserve_cb.setChecked(self.preserve_aspect)
        layout.addWidget(self.preserve_cb)

        # --- DPI UI commented out for now; logic retained below ---
        # self.embed_dpi_cb = QCheckBox("Embed DPI in file")
        # self.embed_dpi_cb.setChecked(self._saved_embed_dpi)
        # self.embed_dpi_cb.setEnabled(self._dpi_supported)
        # if not self._dpi_supported:
        #     self.embed_dpi_cb.setToolTip("DPI embedding is not supported for this file type.")
        # layout.addWidget(self.embed_dpi_cb)
        #
        # dpi_row = QHBoxLayout()
        # dpi_row.addWidget(QLabel("DPI:"))
        # self.dpi_spin = QSpinBox()
        # self.dpi_spin.setRange(1, 2400)
        # self.dpi_spin.setEnabled(self._dpi_supported and self.embed_dpi_cb.isChecked())
        # dpi_default = int(settings.get("resize_default_dpi", 72))
        # self.dpi_spin.setValue(dpi_default)
        # dpi_row.addWidget(self.dpi_spin, 1)
        # layout.addLayout(dpi_row)
        #
        # try:
        #     from pil_image_io import open_pil_with_exif_correction
        #
        #     parent_win = self.parent()
        #     ignore_exif = bool(
        #         getattr(parent_win, "ignore_exif_rotation", False) if parent_win else False
        #     )
        #     probe = open_pil_with_exif_correction(
        #         self.files[0], ignore_exif=ignore_exif, cr2_half_size=False
        #     )
        #     if probe is not None:
        #         try:
        #             d = _read_dpi_from_pil(probe)
        #             if d:
        #                 self.dpi_spin.setValue(d)
        #         finally:
        #             probe.close()
        # except Exception:
        #     pass

        method_row = QHBoxLayout()
        method_row.addWidget(QLabel("Method:"))
        self.method_combo = QComboBox()
        choices = _pil_resampling_choices()
        sel_idx = 0
        for i, (label, _filt) in enumerate(choices):
            self.method_combo.addItem(label, _filt)
            if label == self._saved_resample_label:
                sel_idx = i
        self.method_combo.setCurrentIndex(sel_idx)
        method_row.addWidget(self.method_combo, 1)
        layout.addLayout(method_row)

        self.preserve_dates_cb = QCheckBox("Preserve date (copy original modification time to output)")
        self.preserve_dates_cb.setChecked(self._saved_preserve_dates)
        layout.addWidget(self.preserve_dates_cb)

        self.delete_original_cb = QCheckBox("Delete original file (replace in place)")
        self.delete_original_cb.setChecked(self._saved_delete_original)
        self.delete_original_cb.setToolTip(
            "When checked, each selected image is overwritten. When unchecked, a copy is saved "
            "using the same name pattern as Create Screen Size Copy (e.g. name-0001.ext) and the original is kept."
        )
        layout.addWidget(self.delete_original_cb)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setDefault(True)
        cancel_btn.clicked.connect(self.reject)
        resize_btn = QPushButton("Resize")
        resize_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(resize_btn)
        layout.addLayout(btn_row)

        button_style = get_button_style()
        cancel_btn.setStyleSheet(button_style)
        resize_btn.setStyleSheet(button_style)

        self.width_spin.valueChanged.connect(self._on_width_changed)
        self.height_spin.valueChanged.connect(self._on_height_changed)
        self.preserve_cb.toggled.connect(self._on_preserve_toggled)
        self.dims_radio.toggled.connect(self._on_mode_changed)
        self.percent_radio.toggled.connect(self._on_mode_changed)
        self.percent_slider.valueChanged.connect(self._on_percent_changed)
        # self.embed_dpi_cb.toggled.connect(self._on_embed_dpi_toggled)

        self._set_mode_controls_enabled()

        if self.preserve_cb.isChecked():
            if self._anchor_is_width:
                self._apply_preserve_from_width()
            else:
                self._apply_preserve_from_height()
        self._update_final_size_label()

    # def _on_embed_dpi_toggled(self, checked: bool) -> None:
    #     self.dpi_spin.setEnabled(bool(checked) and self._dpi_supported)

    def _on_preserve_toggled(self, checked: bool) -> None:
        if checked:
            self._anchor_is_width = True
            self._apply_preserve_from_width()

    def _dim_spin_max(self) -> int:
        if self._percent_mode_allowed():
            return MAX_RESIZE_DIMENSION
        return max(self.ref_width, self.ref_height)

    def _apply_preserve_from_width(self) -> None:
        if not self.preserve_cb.isChecked():
            return
        cap = self._dim_spin_max()
        self._updating = True
        try:
            w = int(self.width_spin.value())
            h = max(1, int(round(self.ref_height * w / float(self.ref_width))))
            h = min(h, cap)
            if h == cap and self.ref_height > 0:
                w = min(cap, max(1, int(round(self.ref_width * h / float(self.ref_height)))))
                self.width_spin.setValue(w)
            self.height_spin.setValue(h)
        finally:
            self._updating = False
        self._update_final_size_label()

    def _apply_preserve_from_height(self) -> None:
        if not self.preserve_cb.isChecked():
            return
        cap = self._dim_spin_max()
        self._updating = True
        try:
            h = int(self.height_spin.value())
            w = max(1, int(round(self.ref_width * h / float(self.ref_height))))
            w = min(w, cap)
            if w == cap and self.ref_width > 0:
                h = min(cap, max(1, int(round(self.ref_height * w / float(self.ref_width)))))
                self.height_spin.setValue(h)
            self.width_spin.setValue(w)
        finally:
            self._updating = False
        self._update_final_size_label()

    def _on_width_changed(self, _v: int) -> None:
        if self._updating or not self.preserve_cb.isChecked():
            self._update_final_size_label()
            return
        self._anchor_is_width = True
        self._apply_preserve_from_width()

    def _on_height_changed(self, _v: int) -> None:
        if self._updating or not self.preserve_cb.isChecked():
            self._update_final_size_label()
            return
        self._anchor_is_width = False
        self._apply_preserve_from_height()

    @staticmethod
    def _screen_pixel_size() -> Tuple[int, int]:
        app = QGuiApplication.instance()
        if app is None:
            return 1024, 1024
        screen = app.primaryScreen()
        if screen is None:
            return 1024, 1024
        geom = screen.geometry()
        return int(geom.width()), int(geom.height())

    def _set_dim_spins(self, width: int, height: int) -> None:
        spin_hi = self._dim_spin_max()
        w = max(1, min(spin_hi, int(width)))
        h = max(1, min(spin_hi, int(height)))
        self._updating = True
        try:
            self.width_spin.setValue(w)
            self.height_spin.setValue(h)
        finally:
            self._updating = False
        self._update_final_size_label()

    def _on_screen_size_dims(self) -> None:
        sw, sh = self._screen_pixel_size()
        self._set_dim_spins(sw, sh)

    def _on_square_dims(self) -> None:
        spin_hi = self._dim_spin_max()
        side = max(1, min(spin_hi, int(self.width_spin.value())))
        self._set_dim_spins(side, side)

    def _on_reverse_dims(self) -> None:
        w = int(self.width_spin.value())
        h = int(self.height_spin.value())
        self._set_dim_spins(h, w)

    def accept(self) -> None:
        if self.percent_radio.isChecked() and self._percent_mode_allowed():
            self.use_percent_scale = True
            self.percent_scale = int(self.percent_slider.value())
            self.result_width, self.result_height = self._dimensions_from_percent(self.percent_scale)
            self.preserve_aspect = True
            self._anchor_is_width = True
        else:
            self.use_percent_scale = False
            self.result_width = int(self.width_spin.value())
            self.result_height = int(self.height_spin.value())
            self.preserve_aspect = self.preserve_cb.isChecked()
        self.resample_filter = int(self.method_combo.currentData())
        self.embed_dpi = False
        self.dpi_value = None
        self.delete_original = bool(self.delete_original_cb.isChecked())
        self.preserve_dates = bool(self.preserve_dates_cb.isChecked())

        if self.result_width < 1 or self.result_height < 1:
            show_styled_warning(self, "Resize", "Width and height must be at least 1 pixel.")
            return
        if self.result_width > MAX_RESIZE_DIMENSION or self.result_height > MAX_RESIZE_DIMENSION:
            show_styled_warning(
                self,
                "Resize",
                f"Width and height cannot exceed {MAX_RESIZE_DIMENSION} pixels.",
            )
            return

        cfg = get_config()
        st = cfg.load_settings()
        st["resize_preserve_aspect"] = self.preserve_aspect
        st["resize_resample_method"] = self.method_combo.currentText()
        # st["resize_embed_dpi"] = bool(self.embed_dpi_cb.isChecked())
        # st["resize_default_dpi"] = int(self.dpi_spin.value())
        st["resize_delete_original"] = self.delete_original
        st["resize_preserve_dates"] = self.preserve_dates
        st["resize_anchor_is_width"] = self._anchor_is_width
        cfg.save_settings(st)

        super().accept()


def resize_selected_images(main_window, files: List[str]) -> bool:
    """Show resize UI and resize files in place. Returns True if any file changed."""
    if not files:
        return False

    from exif.exif_image_loader import get_image_dimensions_fast_metadata

    ref = get_image_dimensions_fast_metadata(files[0])
    if not ref:
        show_styled_warning(main_window, "Resize", "Could not read image dimensions for the selection.")
        return False
    ref_w, ref_h = ref

    dlg = ResizeImagesDialog(main_window, files, ref_w, ref_h)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False

    target_w = dlg.result_width
    target_h = dlg.result_height
    preserve = dlg.preserve_aspect
    anchor_is_width = dlg._anchor_is_width
    scale_percent = dlg.percent_scale if dlg.use_percent_scale else None
    resample = dlg.resample_filter
    dpi_val = dlg.dpi_value
    embed_dpi = dlg.embed_dpi
    delete_original = dlg.delete_original
    preserve_dates = dlg.preserve_dates

    ignore_exif = bool(getattr(main_window, "ignore_exif_rotation", False))

    total = len(files)
    progress: Optional[QProgressDialog] = None
    cancel_after_current = False

    if total > 5:
        progress = QProgressDialog("", "Cancel", 0, total, main_window)
        progress.setWindowTitle("Resize Images" if total > 1 else "Resize Image")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        def _mark_cancel() -> None:
            nonlocal cancel_after_current
            cancel_after_current = True

        progress.canceled.connect(_mark_cancel)
        wrap_progress_dialog_label_elision(progress)
        progress.show()
        QApplication.processEvents()

    ok_count = 0
    fail_msgs: List[str] = []
    paths_changed: List[str] = []

    for idx, path in enumerate(files):
        if cancel_after_current:
            break
        if progress:
            progress.setLabelText(f"Resizing {idx + 1} of {total}")
            progress.setValue(idx)
            QApplication.processEvents()

        lm = getattr(main_window, "lock_manager", None)
        if lm and getattr(lm, "is_file_locked", None) and lm.is_file_locked(path):
            fail_msgs.append(f"{os.path.basename(path)}: file is locked")
            continue

        ok, err, wrote, final_path = resize_image_file(
            path,
            target_w,
            target_h,
            preserve,
            anchor_is_width,
            resample,
            dpi_val,
            embed_dpi,
            ignore_exif,
            delete_original,
            preserve_dates,
            scale_percent=scale_percent,
        )
        if ok and wrote and final_path:
            ok_count += 1
            paths_changed.append(final_path)
        elif not ok:
            if err:
                fail_msgs.append(f"{os.path.basename(path)}: {err}")
            else:
                fail_msgs.append(f"{os.path.basename(path)}: resize failed")

        if progress:
            progress.setValue(idx + 1)
            QApplication.processEvents()

    if progress:
        progress.setValue(total)
        progress.close()

    for p in dict.fromkeys(paths_changed):
        if getattr(main_window, "cache_manager", None):
            main_window.cache_manager.clear_cache_for_file(p)
        if getattr(main_window, "thumbnail_container", None) and getattr(
            main_window.thumbnail_container, "canvas", None
        ):
            main_window.thumbnail_container.canvas.invalidate_thumbnails_for_paths([p])

    if fail_msgs:
        max_show = 10
        body = "\n\n".join(fail_msgs[:max_show])
        if len(fail_msgs) > max_show:
            body += f"\n\n... and {len(fail_msgs) - max_show} more"
        show_styled_critical(main_window, "Resize Errors", body)

    if ok_count > 0 and getattr(main_window, "status_notification", None):
        msg = f"Resized {ok_count} {file_string(ok_count)}"
        if cancel_after_current:
            msg += " (stopped early)"
        main_window.status_notification.show_message(msg)

    if ok_count > 0 and hasattr(main_window, "refresh_directory"):
        from PySide6.QtCore import QTimer

        def deferred_refresh() -> None:
            try:
                main_window.refresh_directory(force=True)
            except Exception:
                pass

        QTimer.singleShot(50, deferred_refresh)

    return ok_count > 0
