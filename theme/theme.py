"""Shared Qt stylesheet builders for light/dark theme palettes."""

from __future__ import annotations

from PySide6.QtGui import QColor

from theme.theme_base import asset_url


def macos_scrollbar_handle_hex(track_hex: str, *, theme_id: str, chrome_handle_hex: str) -> str:
    """Contrasting oblong handle color for a scrollbar track."""
    c = QColor(track_hex)
    if not c.isValid():
        return chrome_handle_hex
    lum = (c.red() * 299 + c.green() * 587 + c.blue() * 114) / 1000
    if lum < 50:
        return chrome_handle_hex
    if theme_id == "light":
        return c.darker(130).name()
    if lum > 180:
        return c.darker(115).name()
    return c.lighter(130).name()


def macos_scrollbar_stylesheet(
    *,
    track_bg_hex: str,
    handle_hex: str,
    handle_hover_hex: str,
    selector_prefix: str = "",
) -> str:
    """macOS-like scrollbars: track matches container; rounded handle contrasts with track."""
    prefix = selector_prefix.strip()
    if prefix and not prefix.endswith(" "):
        prefix = f"{prefix} "
    return f"""
    {prefix}QScrollBar:vertical {{
        background-color: {track_bg_hex};
        width: 10px;
        margin: 0px;
    }}
    {prefix}QScrollBar:horizontal {{
        background-color: {track_bg_hex};
        height: 10px;
        margin: 0px;
    }}
    {prefix}QScrollBar::handle:vertical {{
        background-color: {handle_hex};
        min-height: 24px;
        border-radius: 4px;
        margin: 1px;
    }}
    {prefix}QScrollBar::handle:horizontal {{
        background-color: {handle_hex};
        min-width: 24px;
        border-radius: 4px;
        margin: 1px;
    }}
    {prefix}QScrollBar::handle:vertical:hover,
    {prefix}QScrollBar::handle:horizontal:hover {{
        background-color: {handle_hover_hex};
    }}
    {prefix}QScrollBar::add-line:vertical,
    {prefix}QScrollBar::sub-line:vertical,
    {prefix}QScrollBar::add-line:horizontal,
    {prefix}QScrollBar::sub-line:horizontal {{
        background: none;
        border: none;
        height: 0px;
        width: 0px;
    }}
    {prefix}QScrollBar::add-page:vertical,
    {prefix}QScrollBar::sub-page:vertical,
    {prefix}QScrollBar::add-page:horizontal,
    {prefix}QScrollBar::sub-page:horizontal {{
        background-color: {track_bg_hex};
    }}
    """


def macos_scrollbar_for_surface(t, track_bg_hex: str, *, selector_prefix: str = "") -> str:
    """Scrollbar rules with handle contrast derived from track (or chrome fallback)."""
    handle_hex = macos_scrollbar_handle_hex(
        track_bg_hex,
        theme_id=t.theme_id,
        chrome_handle_hex=t.chrome_border_hex,
    )
    return macos_scrollbar_stylesheet(
        track_bg_hex=track_bg_hex,
        handle_hex=handle_hex,
        handle_hover_hex=t.splitter_handle_hover_hex,
        selector_prefix=selector_prefix,
    )


def global_scrollbar_stylesheet(t) -> str:
    """App-wide scrollbar chrome for common container backgrounds."""
    text_edit_bg = "#ffffff" if t.theme_id == "light" else t.default_background_color_hex
    dialog_input_bg = t.dialog_input_background_hex
    tree_bg = text_edit_bg
    return (
        macos_scrollbar_for_surface(t, t.default_background_color_hex)
        + macos_scrollbar_for_surface(t, t.dialog_background_hex, selector_prefix="QDialog")
        + macos_scrollbar_for_surface(t, text_edit_bg, selector_prefix="QTextEdit")
        + macos_scrollbar_for_surface(t, text_edit_bg, selector_prefix="QPlainTextEdit")
        + macos_scrollbar_for_surface(t, dialog_input_bg, selector_prefix="QDialog QLineEdit")
        + macos_scrollbar_for_surface(t, dialog_input_bg, selector_prefix="QDialog QPlainTextEdit")
        + macos_scrollbar_for_surface(t, dialog_input_bg, selector_prefix="QDialog QTextEdit")
        + macos_scrollbar_for_surface(t, dialog_input_bg, selector_prefix="QDialog QSpinBox")
        + macos_scrollbar_for_surface(t, text_edit_bg, selector_prefix="QTextBrowser")
        + macos_scrollbar_for_surface(t, tree_bg, selector_prefix="QTreeView")
        + macos_scrollbar_for_surface(t, t.default_background_color_hex, selector_prefix="QListView")
        + macos_scrollbar_for_surface(t, t.default_background_color_hex, selector_prefix="QListWidget")
    )


def dialog_radio_button_stylesheet(
    t,
    *,
    selector: str = "QRadioButton",
    text_hex: str | None = None,
    indicator_bg_hex: str | None = None,
) -> str:
    """Standard QRadioButton rules (Convert dialog, settings, etc.)."""
    au = asset_url
    color = text_hex if text_hex is not None else t.dialog_text_color_hex
    if indicator_bg_hex is not None:
        indicator_bg = indicator_bg_hex
    elif t.theme_id == "light":
        indicator_bg = "#ffffff"
    else:
        indicator_bg = t.dialog_background_hex
    return f"""
    {selector} {{
        color: {color};
        spacing: 8px;
        background-color: transparent;
    }}
    {selector}::indicator {{
        width: 12px;
        height: 12px;
        border: 2px solid {t.radiobutton_indicator_border_hex};
        border-radius: 8px;
        background-color: {indicator_bg};
    }}
    {selector}::indicator:checked {{
        image: {au("radio_dot.svg")};
    }}
    {selector}::indicator:disabled {{
        border-color: {t.radiobutton_indicator_disabled_hex};
        background-color: {t.radiobutton_indicator_disabled_hex};
    }}
    {selector}::indicator:hover {{
        border-color: {t.checkbox_indicator_hover_border_hex};
    }}
    {selector}::indicator:focus {{
        border-color: {t.checkbox_indicator_focus_border_hex};
    }}
    """


def dialog_input_stylesheet(t) -> str:
    """Editable controls inside QDialog (not settings or unified image-gen shell)."""
    inp = t.dialog_input_background_hex
    dlg_bg = t.dialog_background_hex
    return f"""
    QDialog QLineEdit,
    QDialog QPlainTextEdit {{
        background-color: {inp};
        color: {t.dialog_text_color_hex};
        border: 1px solid {t.border_default_hex};
        border-radius: 4px;
        padding: 6px;
        font-size: 13px;
        selection-background-color: {t.accent_color_hex};
    }}
    QDialog QLineEdit:focus,
    QDialog QPlainTextEdit:focus {{
        background-color: {inp};
        border: {t.current_image_border_width_index}px solid {t.current_image_border_color_hex};
        outline: none;
    }}
    QDialog QLineEdit:hover,
    QDialog QPlainTextEdit:hover {{
        background-color: {inp};
        border: 1px solid {t.border_hover_hex};
    }}
    QDialog QTextEdit {{
        background-color: {inp};
        color: {t.dialog_text_color_hex};
        border: 1px solid {t.border_default_hex};
        selection-background-color: {t.accent_color_hex};
    }}
    QDialog QTextEdit[readOnly="true"],
    QDialog QPlainTextEdit[readOnly="true"] {{
        background-color: {dlg_bg};
    }}
    QDialog QComboBox {{
        background-color: {inp};
        color: {t.dialog_text_color_hex};
    }}
    QDialog QComboBox QAbstractItemView {{
        background-color: {inp};
        color: {t.dialog_text_color_hex};
        selection-background-color: {t.accent_color_hex};
    }}
    QDialog QSpinBox {{
        background-color: {inp};
        color: {t.dialog_text_color_hex};
    }}
    QDialog QSpinBox:disabled {{
        background-color: {dlg_bg};
    }}
    """


def dialog_context_stylesheet(t) -> str:
    """Overrides for dialog children that would otherwise inherit application chrome colors."""
    return f"""
    QDialog QScrollArea {{
        background-color: {t.dialog_background_hex};
    }}
    QDialog QTabBar::tab:!selected {{
        background-color: {t.dialog_background_hex};
    }}
    {dialog_input_stylesheet(t)}
    QDialog QSlider::groove:horizontal {{
        border: 1px solid {t.border_default_hex};
        background: {t.dialog_background_hex};
    }}
    QDialog QSlider::groove:vertical {{
        border: 1px solid {t.border_default_hex};
        background: {t.dialog_background_hex};
    }}
    """


def push_button_stylesheet(
    t,
    selector: str = "QPushButton",
    *,
    min_width: str = "100px",
    padding: str = "6px 18px",
    font_size: str = "13px",
    border_radius: str = "5px",
    pressed_text_hex: str | None = None,
) -> str:
    """Standard QPushButton rules from the active theme palette."""
    disabled_border = t.border_default_hex if t.theme_id == "light" else t.dialog_background_hex
    pressed_color = pressed_text_hex if pressed_text_hex is not None else t.dialog_text_color_hex
    return f"""
    {selector} {{
        background-color: {t.button_bg_default_hex};
        color: {t.button_text_default_hex};
        border: 1px solid {t.button_border_default_hex};
        border-radius: {border_radius};
        padding: {padding};
        min-width: {min_width};
        font-size: {font_size};
        font-family: 'Arial Narrow', Arial;
        letter-spacing: 0.5px;
    }}
    {selector}:default {{
        background-color: {t.button_default_bg_hex};
        color: {t.button_focus_text_hex};
        border: 1px solid {t.button_default_border_hex};
    }}
    {selector}:hover {{
        background-color: {t.button_bg_hover_hex};
        color: {t.button_text_hover_hex};
        border: 1px solid {t.button_border_hover_hex};
    }}
    {selector}:focus {{
        background-color: {t.button_bg_hover_hex};
        color: {t.button_text_hover_hex};
        border: 1px solid {t.button_border_hover_hex};
        outline: none;
    }}
    {selector}:pressed {{
        background-color: {t.button_bg_pressed_hex};
        color: {pressed_color};
    }}
    {selector}:disabled {{
        background-color: {t.widget_bg_disabled_hex};
        color: {t.text_disabled_hex};
        border-color: {disabled_border};
    }}
    """


def spinbox_stylesheet(t) -> str:
    """Native QSpinBox / QDoubleSpinBox container styling (no subcontrol rules on macOS)."""
    border = t.border_default_hex
    return f"""
    QSpinBox, QDoubleSpinBox {{
        font-size: 12px;
        border: 2px solid {border};
        padding: 5px 5px 5px 5px;
        margin-left: 10px;
        border-radius: 4px;
        background-color: transparent;
    }}
    QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 2px solid {t.accent_color_hex};
    }}
    QSpinBox:disabled, QDoubleSpinBox:disabled {{
        border: 2px solid {t.widget_bg_disabled_hex};
        background-color: {t.dialog_background_hex};
        color: {t.spinbox_disabled_text_hex};
        border-color: {t.spinbox_disabled_border_hex};
    }}
    """


def step_spin_box_stylesheet(t) -> str:
    """StepSpinBox composite control with explicit step buttons."""
    border = t.border_default_hex
    return f"""
    StepSpinBox {{
        font-size: 12px;
        border: 2px solid {border};
        margin-left: 10px;
        border-radius: 4px;
        background-color: transparent;
    }}
    StepSpinBox[hasFocus="true"] {{
        border: 2px solid {t.accent_color_hex};
    }}
    StepSpinBox:disabled {{
        border: 2px solid {t.spinbox_disabled_border_hex};
        background-color: {t.dialog_background_hex};
        color: {t.spinbox_disabled_text_hex};
    }}
    StepSpinBox QLineEdit#StepSpinEdit {{
        border: none;
        background: transparent;
        color: inherit;
        padding: 5px 4px 5px 5px;
        margin: 0px;
        selection-background-color: {t.accent_color_hex};
    }}
    StepSpinBox:disabled QLineEdit#StepSpinEdit {{
        color: {t.spinbox_disabled_text_hex};
    }}
    StepSpinBox QWidget#StepSpinButtons {{
        background: transparent;
        min-width: 12px;
        max-width: 12px;
    }}
    StepSpinBox QToolButton#StepSpinUpButton,
    StepSpinBox QToolButton#StepSpinDownButton {{
        border: none;
        border-left: 1px solid {border};
        background: transparent;
        padding: 0px;
        margin: 0px;
        min-width: 12px;
        max-width: 12px;
    }}
    StepSpinBox QToolButton#StepSpinUpButton {{
        border-bottom: 1px solid {border};
        border-top-right-radius: 2px;
    }}
    StepSpinBox QToolButton#StepSpinDownButton {{
        border-bottom-right-radius: 2px;
    }}
    StepSpinBox QToolButton#StepSpinUpButton:hover:enabled,
    StepSpinBox QToolButton#StepSpinDownButton:hover:enabled {{
        background: {t.widget_bg_hover_hex};
    }}
    StepSpinBox QToolButton#StepSpinUpButton:disabled,
    StepSpinBox QToolButton#StepSpinDownButton:disabled {{
        opacity: 0.35;
    }}
    """


def global_stylesheet_light(t) -> str:
    au = asset_url
    return f"""
    QMainWindow {{
        background-color: {t.default_background_color_hex};
        color: {t.dialog_text_color_hex};
    }}
    QWidget {{
        background-color: {t.default_background_color_hex};
        color: {t.dialog_text_color_hex};
    }}
    QDialog {{
        background-color: {t.dialog_background_hex};
        color: {t.dialog_text_color_hex};
    }}
    QDialog QWidget {{
        background-color: {t.dialog_background_hex};
        color: {t.dialog_text_color_hex};
    }}
    QScrollArea {{
        background-color: {t.default_background_color_hex};
        border: none;
    }}

    QMenuBar {{
        background-color: {t.dialog_background_hex};
        color: {t.dialog_text_color_hex};
        border: none;
    }}
    QMenuBar::item {{
        background-color: transparent;
        padding: 4px 8px;
    }}
    QMenuBar::item:selected {{
        background-color: {t.widget_bg_hover_hex};
    }}
    {t.context_menu_stylesheet()}

    QStatusBar {{
        background-color: {t.main_status_bar_bg_hex};
        color: {t.status_bar_label_text_hex};
        border-top: {t.view_border_width_px}px solid {t.chrome_border_hex};
    }}

    QLabel {{
        color: {t.dialog_text_color_hex};
        background: transparent;
        background-color: transparent;
    }}

    {push_button_stylesheet(t)}
    QDialogButtonBox QPushButton {{
        min-width: 80px;
        padding: 6px 14px;
    }}

    QLineEdit {{
        background-color: {t.button_bg_default_hex};
        color: {t.button_text_default_hex};
        border: 1px solid {t.button_border_default_hex};
        border-radius: 5px;
        padding: 6px 12px;
        font-size: 13px;
        font-family: 'Arial Narrow', Arial;
        letter-spacing: 0.5px;
    }}
    QLineEdit:focus {{
        background-color: #ffffff;
        color: {t.dialog_text_color_hex};
        border: {t.current_image_border_width_index}px solid {t.current_image_border_color_hex};
        outline: none;
    }}
    QLineEdit:hover {{
        background-color: {t.button_bg_hover_hex};
        color: {t.button_text_hover_hex};
        border: 1px solid {t.button_border_hover_hex};
    }}

    {spinbox_stylesheet(t)}
    {step_spin_box_stylesheet(t)}

    QComboBox {{
        background-color: #ffffff;
        color: {t.dialog_text_color_hex};
        border: 1px solid {t.border_default_hex};
        border-radius: 4px;
        padding: 6px 12px;
        min-width: 60px;
        max-width: 160px;
    }}
    QComboBox:hover {{
        border-color: {t.border_hover_hex};
    }}
    QComboBox:focus {{
        border-color: {t.accent_color_hex};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 12px;
        padding: 0 2px 0 0 ;
        image: {au("combo_arrow.svg")};
    }}
    QComboBox QAbstractItemView {{
        background-color: #ffffff;
        color: {t.dialog_text_color_hex};
        border: 1px solid {t.border_default_hex};
        selection-background-color: {t.accent_color_hex};
    }}

    QCheckBox {{
        color: {t.dialog_text_color_hex};
        spacing: 8px;
        background-color: transparent;
    }}
    QCheckBox::indicator {{
        width: 12px;
        height: 12px;
        border: 1.5px solid {t.checkbox_indicator_border_hex};
        border-radius: 3px;
        background-color: #ffffff;
    }}
    QCheckBox::indicator:checked {{
        image: {au("checkbox_x.svg")};
    }}
    QCheckBox::indicator:hover {{
        border-color: {t.checkbox_indicator_hover_border_hex};
    }}
    QCheckBox::indicator:focus {{
        border-color: {t.checkbox_indicator_focus_border_hex};
    }}

    QRadioButton {{
        color: {t.dialog_text_color_hex};
        spacing: 8px;
        background-color: transparent;
    }}
    QRadioButton::indicator {{
        width: 12px;
        height: 12px;
        border: 2px solid {t.radiobutton_indicator_border_hex};
        border-radius: 8px;
        background-color: #ffffff;
    }}
    QRadioButton::indicator:checked {{
        image: {au("radio_dot.svg")};
    }}
    QRadioButton::indicator:disabled {{
        border-color: {t.radiobutton_indicator_disabled_hex};
        background-color: {t.radiobutton_indicator_disabled_hex};
    }}
    QRadioButton::indicator:hover {{
        border-color: {t.checkbox_indicator_hover_border_hex};
    }}
    QRadioButton::indicator:focus {{
        border-color: {t.checkbox_indicator_focus_border_hex};
    }}

    QGroupBox {{
        font-weight: bold;
        border: 2px solid {t.groupbox_border_hex};
        border-radius: 5px;
        margin-top: 1ex;
        padding-top: 10px;
        color: {t.dialog_text_color_hex};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px 0 5px;
        color: {t.dialog_text_color_hex};
    }}

    QTabWidget::pane {{
        border: 1px solid {t.groupbox_border_hex};
        background-color: {t.dialog_background_hex};
        border-radius: 5px;
    }}
    QTabBar::tab {{
        background-color: {t.default_background_color_hex};
        color: {t.dialog_text_color_hex};
        border: 1px solid {t.groupbox_border_hex};
        border-bottom: none;
        padding: 5px 15px;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background-color: {t.accent_color_hex};
        border-color: {t.tab_button_focus_border_color_hex};
        color: #ffffff;
    }}
    QTabBar::tab:!selected {{
        margin-top: 2px;
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {t.widget_bg_hover_hex};
    }}

    QSlider::groove:horizontal {{
        border: 1px solid {t.border_default_hex};
        height: 6px;
        background: {t.default_background_color_hex};
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {t.accent_color_hex};
        border: 1px solid {t.tab_button_focus_border_color_hex};
        width: 16px;
        height: 16px;
        margin: -5px 0;
        border-radius: 8px;
    }}
    QSlider::handle:horizontal:hover {{
        background: {t.tab_button_focus_border_color_hex};
        border-color: {t.qslider_handle_hover_border_hex};
    }}
    QSlider::handle:horizontal:focus {{
        border: 2px solid {t.qslider_handle_focus_border_hex};
    }}
    QSlider::sub-page:horizontal {{
        background: {t.accent_color_hex};
        border-radius: 3px;
    }}

    QTextEdit {{
        background-color: #ffffff;
        color: {t.dialog_text_color_hex};
        border: 1px solid {t.border_default_hex};
        border-radius: 4px;
        padding: 5px;
    }}
    QTextEdit:focus {{
        border-color: {t.accent_color_hex};
    }}

    QMessageBox {{
        background-color: {t.dialog_background_hex};
        color: {t.dialog_text_color_hex};
    }}
    QMessageBox QLabel {{
        color: {t.dialog_text_color_hex};
        background: transparent;
        background-color: transparent;
    }}

    QToolTip {{
        background-color: {t.qtooltip_bg_hex};
        color: {t.qtooltip_fg_hex};
        border: 1px solid {t.qtooltip_border_hex};
        border-radius: 4px;
        padding: 1px 1px;
    }}

    QTreeView {{
        background-color: #ffffff;
        border: 1px solid {t.tree_view_border_hex};
        border-radius: 3px;
        selection-background-color: {t.tree_view_selection_bg_hex};
        outline: none;
        color: {t.tree_view_text_hex};
        font-weight: normal;
        show-decoration-selected: 1;
        letter-spacing: 0.8px;
    }}
    QTreeView::branch {{
        background: transparent;
    }}
    QTreeView::item {{
        padding: 0px 4px;
        border: none;
        min-height: 10px;
        background-color: #ffffff;
    }}
    QTreeView::item:selected {{
        background-color: {t.tree_view_selection_bg_hex};
        color: {t.dialog_text_color_hex};
    }}
    QTreeView::item:hover {{
        background-color: {t.tree_view_item_hover_hex};
    }}
    QHeaderView::section {{
        background-color: {t.tree_header_section_bg_hex};
        color: {t.dialog_text_color_hex};
        padding: 2px 4px;
        border: 1px solid {t.tree_view_border_hex};
        font-weight: bold;
    }}

    QProgressBar {{
        border: 1px solid {t.border_default_hex};
        border-radius: 4px;
        text-align: center;
        background-color: {t.default_background_color_hex};
        color: {t.dialog_text_color_hex};
    }}
    QProgressBar::chunk {{
        background-color: {t.accent_color_hex};
        border-radius: 3px;
    }}

    {dialog_context_stylesheet(t)}
    {global_scrollbar_stylesheet(t)}
    """.strip()

def global_stylesheet_dark(t) -> str:
    au = asset_url
    return f"""
    /* Main Window and Base Widgets */
    QMainWindow {{
        background-color: {t.default_background_color_hex};
        color: {t.dialog_text_color_hex};
    }}
    QWidget {{
        background-color: {t.default_background_color_hex};
        color: {t.dialog_text_color_hex};
    }}
    QDialog {{
        background-color: {t.dialog_background_hex};
        color: {t.dialog_text_color_hex};
    }}
    QDialog QWidget {{
        background-color: {t.dialog_background_hex};
        color: {t.dialog_text_color_hex};
    }}
    QScrollArea {{
        background-color: {t.default_background_color_hex};
        border: none;
    }}

    /* Menu Bar */
    QMenuBar {{
        background-color: {t.dialog_background_hex};
        color: {t.dialog_text_color_hex};
        border: none;
    }}
    QMenuBar::item {{
        background-color: transparent;
        padding: 4px 8px;
    }}
    QMenuBar::item:selected {{
        background-color: {t.widget_bg_hover_hex};
    }}
    {t.context_menu_stylesheet()}

    /* Status Bar */
    QStatusBar {{
        background-color: {t.main_status_bar_bg_hex};
        color: {t.status_bar_label_text_hex};
        border-top: {t.view_border_width_px}px solid {t.chrome_border_hex};
    }}

    /* Labels */
    QLabel {{
        color: {t.dialog_text_color_hex};
        background: transparent;
        background-color: transparent;
    }}

    /* Buttons */
    {push_button_stylesheet(t)}
    QDialogButtonBox QPushButton {{
        min-width: 80px;
        padding: 6px 14px;
    }}

    /* Input Fields */
    QLineEdit {{
        background-color: {t.button_bg_default_hex};
        color: {t.button_focus_text_hex};
        border: 1px solid {t.button_border_default_hex};
        border-radius: 5px;
        padding: 6px 12px;
        font-size: 13px;
        font-family: 'Arial Narrow', Arial;
        letter-spacing: 0.5px;
    }}
    QLineEdit:focus {{
        background-color: {t.button_bg_default_hex};
        color: {t.dialog_text_color_hex};
        border: {t.current_image_border_width_index}px solid {t.current_image_border_color_hex};
        outline: none;
    }}
    QLineEdit:hover {{
        background-color: {t.button_bg_hover_hex};
        color: {t.button_text_hover_hex};
        border: 1px solid {t.button_border_hover_hex};
    }}

    {spinbox_stylesheet(t)}
    {step_spin_box_stylesheet(t)}

    /* Combo Box */
    QComboBox {{
        background-color: {t.default_background_color_hex};
        color: {t.dialog_text_color_hex};
        border: 1px solid {t.border_default_hex};
        border-radius: 4px;
        padding: 6px 12px;
        min-width: 60px;
        max-width: 160px;
    }}
    QComboBox:hover {{
        border-color: {t.border_hover_hex};
    }}
    QComboBox:focus {{
        border-color: {t.accent_color_hex};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 12px;
        padding: 0 2px 0 0 ;
        image: {au("combo_arrow.svg")};
    }}
    QComboBox QAbstractItemView {{
        background-color: {t.default_background_color_hex};
        color: {t.dialog_text_color_hex};
        border: 1px solid {t.border_default_hex};
        selection-background-color: {t.accent_color_hex};
    }}

    /* Checkbox */
    QCheckBox {{
        color: {t.dialog_text_color_hex};
        spacing: 8px;
        background-color: transparent;
    }}
    QCheckBox::indicator {{
        width: 12px;
        height: 12px;
        border: 1.5px solid {t.checkbox_indicator_border_hex};
        border-radius: 3px;
        background-color: black;
    }}
    QCheckBox::indicator:checked {{
        image: {au("checkbox_x.svg")};
    }}
    QCheckBox::indicator:hover {{
        border-color: {t.checkbox_indicator_hover_border_hex};
    }}
    QCheckBox::indicator:focus {{
        border-color: {t.checkbox_indicator_focus_border_hex};
    }}

    /* Radio Button */
    QRadioButton {{
        color: {t.dialog_text_color_hex};
        spacing: 8px;
        background-color: transparent;
    }}
    QRadioButton::indicator {{
        width: 12px;
        height: 12px;
        border: 2px solid {t.radiobutton_indicator_border_hex};
        border-radius: 8px;
        background-color: {t.dialog_background_hex};
    }}
    QRadioButton::indicator:checked {{
        image: {au("radio_dot.svg")};
    }}
    QRadioButton::indicator:disabled {{
        border-color: {t.radiobutton_indicator_disabled_hex};
        background-color: {t.radiobutton_indicator_disabled_hex};
    }}
    QRadioButton::indicator:hover {{
        border-color: {t.checkbox_indicator_hover_border_hex};
    }}
    QRadioButton::indicator:focus {{
        border-color: {t.checkbox_indicator_focus_border_hex};
    }}

    /* Group Box */
    QGroupBox {{
        font-weight: bold;
        border: 2px solid {t.groupbox_border_hex};
        border-radius: 5px;
        margin-top: 1ex;
        padding-top: 10px;
        color: {t.dialog_text_color_hex};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px 0 5px;
        color: {t.dialog_text_color_hex};
    }}

    /* Tab Widget */
    QTabWidget::pane {{
        border: 1px solid {t.groupbox_border_hex};
        background-color: {t.dialog_background_hex};
        border-radius: 5px;
    }}
    QTabBar::tab {{
        background-color: {t.default_background_color_hex};
        color: {t.dialog_text_color_hex};
        border: 1px solid {t.groupbox_border_hex};
        border-bottom: none;
        padding: 5px 15px;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background-color: {t.accent_color_hex};
        border-color: {t.tab_button_focus_border_color_hex};
    }}
    QTabBar::tab:!selected {{
        margin-top: 2px;
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {t.widget_bg_hover_hex};
    }}

    /* Slider */
    QSlider::groove:horizontal {{
        border: 1px solid {t.border_default_hex};
        height: 6px;
        background: {t.default_background_color_hex};
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {t.accent_color_hex};
        border: 1px solid {t.tab_button_focus_border_color_hex};
        width: 16px;
        height: 16px;
        margin: -5px 0;
        border-radius: 8px;
    }}
    QSlider::handle:horizontal:hover {{
        background: {t.tab_button_focus_border_color_hex};
        border-color: {t.qslider_handle_hover_border_hex};
    }}
    QSlider::handle:horizontal:focus {{
        border: 2px solid {t.qslider_handle_focus_border_hex};
    }}
    QSlider::sub-page:horizontal {{
        background: {t.accent_color_hex};
        border-radius: 3px;
    }}

    /* Text Edit */
    QTextEdit {{
        background-color: {t.default_background_color_hex};
        color: {t.dialog_text_color_hex};
        border: 1px solid {t.border_default_hex};
        border-radius: 4px;
        padding: 5px;
    }}
    QTextEdit:focus {{
        border-color: {t.accent_color_hex};
    }}

    /* Message Box */
    QMessageBox {{
        background-color: {t.dialog_background_hex};
        color: {t.dialog_text_color_hex};
    }}
    QMessageBox QLabel {{
        color: {t.dialog_text_color_hex};
        background: transparent;
        background-color: transparent;
    }}

    /* Tooltip */
    QToolTip {{
        background-color: {t.qtooltip_bg_hex};
        color: {t.qtooltip_fg_hex};
        border: 1px solid {t.qtooltip_border_hex};
        border-radius: 4px;
        padding: 1px 1px;
    }}

    /* Tree View */
    QTreeView {{
        background-color: {t.default_background_color_hex};
        border: 1px solid {t.tree_view_border_hex};
        border-radius: 3px;
        selection-background-color: {t.tree_view_selection_bg_hex};
        outline: none;
        color: {t.tree_view_text_hex};
        font-weight: 100;
        show-decoration-selected: 1;
        letter-spacing: 0.8px;
    }}
    QTreeView::branch {{
        background: transparent;
    }}
    QTreeView::item {{
        padding: 0px 4px;
        border: none;
        min-height: 10px;
        background-color: {t.default_background_color_hex};
    }}
    QTreeView::item:selected {{
        background-color: {t.tree_view_selection_bg_hex};
        color: {t.dialog_text_color_hex};
    }}
    QTreeView::item:hover {{
        background-color: {t.tree_view_item_hover_hex};
    }}
    QHeaderView::section {{
        background-color: {t.tree_header_section_bg_hex};
        color: {t.dialog_text_color_hex};
        padding: 2px 4px;
        border: 1px solid {t.tree_view_border_hex};
        font-weight: bold;
    }}

    /* Progress Bar */
    QProgressBar {{
        border: 1px solid {t.border_default_hex};
        border-radius: 4px;
        text-align: center;
        background-color: {t.default_background_color_hex};
        color: {t.dialog_text_color_hex};
    }}
    QProgressBar::chunk {{
        background-color: {t.accent_color_hex};
        border-radius: 3px;
    }}

    {dialog_context_stylesheet(t)}
    {global_scrollbar_stylesheet(t)}
    """.strip()

class ThemeStylesMixin:
    """Stylesheet methods shared by LightTheme and DarkTheme (palette via `self`)."""

    def context_menu_stylesheet(
        self, *, rounded: bool = False, anchored_top: bool = False
    ) -> str:
        """QMenu rules using status bar background, text, selection, and disabled colors."""
        from thumbnails import thumbnail_constants as tc

        t = self
        selected_bg = t.status_bar_menu_item_selected_bg_hex()
        item_h = tc.QMENU_ITEM_MIN_HEIGHT
        pad_v = tc.QMENU_ITEM_PADDING_V
        pad_h = tc.QMENU_ITEM_PADDING_H
        text_left = (
            tc.QMENU_INDICATOR_LEFT + tc.QMENU_INDICATOR_SIZE + tc.QMENU_ITEM_TEXT_LEFT
        )
        ind_size = tc.QMENU_INDICATOR_SIZE
        ind_left = tc.QMENU_INDICATOR_LEFT
        font_pt = tc.QMENU_FONT_SIZE_PT
        sep_margin_h = max(8, pad_h // 2)

        if anchored_top:
            shell_border = f"""
        border-top: 1px solid {t.chrome_border_hex};
        border-left: 1px solid {t.chrome_border_hex};
        border-right: 1px solid {t.chrome_border_hex};
        border-bottom: 0px solid {t.chrome_border_hex};
        padding: 2px;"""
        else:
            shell_border = f"border: 1px solid {t.border_default_hex};"
            if rounded:
                shell_border += """
        border-radius: 7px;
        padding-top: 7px;
        padding-bottom: 7px;"""

        return f"""
    QMenu {{
        background-color: {t.main_status_bar_bg_hex};
        color: {t.status_bar_label_text_hex};{shell_border}
    }}
    QMenu::item {{
        min-height: {item_h}px;
        font-size: {font_pt}pt;
        font-weight: 500;
        color: {t.status_bar_label_text_hex};
        background-color: transparent;
        padding: {pad_v}px {pad_h}px {pad_v}px {text_left}px;
    }}
    QMenu::item:selected {{
        background-color: {selected_bg};
        color: {t.status_bar_label_text_hex};
    }}
    QMenu::item:disabled {{
        color: {t.status_bar_label_disabled_hex};
        font-weight: 100;
    }}
    QMenu::indicator {{
        width: {ind_size}px;
        height: {ind_size}px;
        left: {ind_left}px;
    }}
    QMenu::separator {{
        height: 1px;
        background: {t.status_bar_label_disabled_hex};
        margin: 5px {sep_margin_h}px;
    }}
    """

    def qmenu_stylesheet(self) -> str:
        return self.context_menu_stylesheet(rounded=True)

    def heading_color_hex(self) -> str:
        if self.theme_id == "light":
            return QColor(self.text_color_hex).darker(108).name()
        return QColor(self.text_color_hex).lighter(115).name()

    def dialog_heading_color_hex(self) -> str:
        if self.theme_id == "light":
            return QColor(self.dialog_text_color_hex).darker(108).name()
        return QColor(self.dialog_text_color_hex).lighter(115).name()

    def sidebar_heading_color_hex(self) -> str:
        if self.theme_id == "light":
            return QColor(self.sidebar_text_color_hex).darker(108).name()
        return QColor(self.sidebar_text_color_hex).lighter(115).name()

    def global_stylesheet(self) -> str:
        if self.theme_id == "light":
            return global_stylesheet_light(self)
        return global_stylesheet_dark(self)

    def main_splitter_stylesheet(self) -> str:
        t = self
        return f"""
            QSplitter::handle {{
                background-color: {t.chrome_border_hex};
                border: none;
                margin: 0px;
            }}
            QSplitter::handle:hover {{
                background-color: {t.splitter_handle_hover_hex};
                border: none;
            }}
            QSplitter::handle:pressed {{
                background-color: {t.splitter_handle_pressed_hex};
                border: none;
            }}
        """

    def chrome_splitter_stylesheet(self) -> str:
        """View borders color + splitter/status bar width (theme settings Sidebar & chrome)."""
        w = self.view_border_width_px
        return (
            self.main_splitter_stylesheet()
            + f"""
            QSplitter::handle:horizontal {{
                width: {w}px;
            }}
            QSplitter::handle:vertical {{
                height: {w}px;
            }}
        """
        )

    def main_status_bar_chrome_stylesheet(self) -> str:
        t = self
        return f"""
            QStatusBar {{
                border: none;
                border-top: {t.view_border_width_px}px solid {t.chrome_border_hex};
                background-color: {t.main_status_bar_bg_hex};
                color: {t.status_bar_label_text_hex};
                padding: 0px;
                margin: 0px;
            }}
            QStatusBar::item {{
                border: none;
                background-color: transparent;
            }}
        """

    def floating_progress_bar_stylesheet(self) -> str:
        t = self
        return f"""
            QProgressBar {{
                border: 1px solid {t.progress_bar_border_hex};
                border-radius: 0px;
                text-align: center;
                background-color: {t.progress_bar_bg_hex};
                color: {t.progress_bar_text_hex};
                font-size: 14px;
                font-weight: normal;
                padding: 2px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 {t.progress_chunk_gradient_start}, stop: 0.5 {t.progress_chunk_gradient_mid}, stop: 1 {t.progress_chunk_gradient_end});
                border-radius: 0px;
            }}
        """

    def thumbnail_status_label_stylesheet(self) -> str:
        return f"""
            QLabel {{
                color: {self.thumbnail_status_label_text_hex};
                background-color: transparent;
                padding: 2px 5px;
            }}
        """

    def browse_view_shell_stylesheet(self) -> str:
        t = self
        return f"""
            QWidget {{
                background-color: rgb({t.browse_view_bg_rgb});
                color: {t.browse_view_fg_hex};
            }}
        """

    def browse_filename_textedit_stylesheet(self) -> str:
        t = self
        return f"""
            QTextEdit {{
                background-color: rgba({t.browse_filename_bg_rgba});
                border: 2px solid {t.browse_filename_border_hex};
                border-radius: 0px;
                color: {t.browse_filename_text_hex};
                font-family: "Courier New", "Monaco", "Menlo";
                font-size: 12pt;
                font-weight: normal;
                padding: 15px 18px;
            }}
        """

    def browse_filename_document_stylesheet(self) -> str:
        return f"color: {self.browse_filename_doc_color_hex}; font-size: 12pt;"

    def status_bar_menu_item_selected_bg_hex(self) -> str:
        """Row highlight for status-bar popup menus (derived from status bar fill)."""
        q = QColor(self.main_status_bar_bg_hex)
        if not q.isValid():
            return self.status_menu_selected_hex
        if self.theme_id == "light":
            return q.darker(112).name()
        return q.lighter(130).name()

    def status_bar_context_menu_stylesheet(self) -> str:
        return self.context_menu_stylesheet(anchored_top=True)

    def file_tree_panel_stylesheet(self) -> str:
        """Embedded file tree (left sidebar) — distinct from generic QTreeView in global sheet."""
        t = self
        fw = "normal" if self.theme_id == "light" else "100"
        body_text = t.sidebar_text_color_hex
        heading_text = t.sidebar_heading_color_hex()
        sidebar_bg = t.sidebar_background_color_hex
        return f"""
            QTreeView {{
                background-color: {sidebar_bg};
                border: 1px solid {t.tree_view_border_hex};
                border-radius: 3px;
                selection-background-color: {t.tree_view_selection_bg_hex};
                outline: none;
                color: {t.tree_view_text_hex};
                font-weight: {fw};
                show-decoration-selected: 1;
                letter-spacing: 0.8px;
            }}
            QTreeView::branch {{
                background: transparent;
            }}
            QTreeView::item {{
                padding: 0px 4px;
                border: none;
                height: 15px;
                min-height: 10px;
                background-color: {sidebar_bg};
            }}
            QTreeView::item:selected {{
                background-color: {t.tree_view_selection_bg_hex};
                color: {body_text};
            }}
            QTreeView::item[highlighted="true"] {{
                background-color: {t.file_tree_item_highlighted_bg_hex};
                color: {body_text};
                font-weight: bold;
            }}
            QTreeView::item[highlighted="true"]:selected {{
                background-color: {t.file_tree_item_highlighted_selected_bg_hex};
                color: {body_text};
                font-weight: bold;
            }}
            QTreeView::item:hover {{
                background-color: {t.tree_view_item_hover_hex};
            }}
            QHeaderView::section {{
                background-color: {t.tree_header_section_bg_hex};
                color: {heading_text};
                padding: 2px 4px;
                border: 1px solid {t.tree_view_border_hex};
                font-weight: bold;
            }}
            {macos_scrollbar_stylesheet(
                track_bg_hex=sidebar_bg,
                handle_hex=t.chrome_border_hex,
                handle_hover_hex=t.splitter_handle_hover_hex,
                selector_prefix="QTreeView",
            )}
        """

    def file_tree_pane_shell_stylesheet(self) -> str:
        """Outer file-tree pane widgets (shell around nav bar, path label, and tree)."""
        return f"QWidget {{ background-color: {self.sidebar_background_color_hex}; }}"

    def _file_tree_control_surface_hex(self) -> str:
        """Nav/filter icon chips: slightly distinct from pane background."""
        q = QColor(self.sidebar_background_color_hex)
        if not q.isValid():
            return self.file_tree_nav_button_bg_hex
        if self.theme_id == "light":
            return q.darker(108).name()
        return q.lighter(110).name()

    def _file_tree_control_surface_hover_hex(self) -> str:
        q = QColor(self._file_tree_control_surface_hex())
        if not q.isValid():
            return self.file_tree_nav_button_hover_hex
        if self.theme_id == "light":
            return q.darker(112).name()
        return q.lighter(125).name()

    def file_tree_nav_container_stylesheet(self) -> str:
        return f"""
            background-color: {self.sidebar_background_color_hex};
            border-radius: 4px;
        """

    def file_tree_nav_icon_button_stylesheet(
        self, focus_bg: str, focus_border: str, focus_text: str, *, dim: bool = False
    ) -> str:
        t = self
        fg = t.file_tree_nav_button_text_dim_hex if dim else t.file_tree_nav_button_text_hex
        btn_bg = t._file_tree_control_surface_hex()
        btn_hover = t._file_tree_control_surface_hover_hex()
        btn_pressed = (
            QColor(btn_bg).darker(112).name()
            if t.theme_id == "light"
            else QColor(btn_bg).lighter(108).name()
        )
        return f"""
            QPushButton {{
                background-color: {btn_bg};
                color: {fg};
                border: 1px solid {t.file_tree_nav_button_border_hex};
                border-radius: 3px;
                padding: 2px;
                font-size: 12px;
                min-width: 0px;
            }}
            QPushButton:hover {{ background-color: {btn_hover}; }}
            QPushButton:pressed {{ background-color: {btn_pressed}; }}
            QPushButton:focus {{
                background-color: {focus_bg};
                border: 1px solid {focus_border};
                color: {focus_text};
            }}
        """

    def file_tree_current_dir_label_stylesheet(self) -> str:
        t = self
        return f"""
            QLabel {{
                color: {t.sidebar_text_color_hex};
                font-size: 12px;
                padding: 2px 5px;
                background-color: {t.sidebar_background_color_hex};
                border: 1px solid {t.file_tree_dir_label_border_hex};
                border-radius: 3px;
            }}
        """

    def file_tree_filter_mode_button_stylesheet(self, size: int) -> str:
        t = self
        s = size
        icon_c = "#1a1a1a" if self.theme_id == "light" else "#ffffff"
        btn_bg = t._file_tree_control_surface_hex()
        btn_hover = t._file_tree_control_surface_hover_hex()
        return f"""
            QPushButton {{
                background-color: {btn_bg};
                color: {icon_c};
                border-width: 1px;
                border-style: solid;
                border-color: {t.file_tree_filter_btn_border_hex};
                border-radius: 0px;
                min-width: {s}px;
                max-width: {s}px;
                min-height: {s}px;
                max-height: {s}px;
                padding: 0px;
            }}
            QPushButton:checked {{
                background-color: {btn_bg};
                border-color: {t.file_tree_filter_btn_border_hex};
            }}
            QPushButton:hover {{
                background-color: {btn_hover};
            }}
            QPushButton:checked:hover {{
                background-color: {btn_hover};
            }}
        """

    def file_tree_filter_separator_stylesheet(self) -> str:
        return f"QFrame {{ background-color: {self.file_tree_filter_sep_hex}; max-width: 1px; }}"

    def shortcuts_sidebar_widget_stylesheet(self) -> str:
        return f"QWidget {{ background-color: {self.sidebar_background_color_hex}; }}"

    def sidebar_pane_scroll_area_stylesheet(self, track_bg_hex: str | None = None) -> str:
        """Right-sidebar QScrollArea: pane-colored track with macOS-like oval handles."""
        t = self
        track = track_bg_hex or t.sidebar_background_color_hex
        return f"""
            QScrollArea {{
                background-color: {track};
                border: none;
            }}
            QScrollArea > QWidget {{
                background-color: {track};
            }}
            {macos_scrollbar_for_surface(t, track)}
        """

    def shortcuts_sidebar_scroll_stylesheet(self) -> str:
        return self.sidebar_pane_scroll_area_stylesheet()

    def sidebar_jobs_scroll_stylesheet(self) -> str:
        return self.sidebar_pane_scroll_area_stylesheet()

    def thumbnail_scroll_area_chrome_stylesheet(self, object_name: str = "thumbnailScrollArea") -> str:
        """Thumbnail grid scroll area: grid fill throughout; scrollbar track matches grid."""
        t = self
        grid_hex = t.thumbnail_grid_background_color_hex
        prefix = f"#{object_name}"
        return f"""
            {prefix} {{
                background-color: {grid_hex};
                border: none;
            }}
            {macos_scrollbar_for_surface(t, grid_hex, selector_prefix=prefix)}
        """

    def shortcuts_sidebar_combo_stylesheet(self) -> str:
        t = self
        return f"""
            QComboBox {{
                color: {t.sidebar_text_color_hex};
                background-color: {t.shortcuts_combo_bg_hex};
                border: 1px solid {t.shortcuts_combo_border_hex};
                border-radius: 2px;
                padding: 3px 8px;
                font-size: 12pt;
                width:70px;
                max-width: 70px;
                min-width: 70px;
            }}
            QComboBox:hover {{ border-color: {t.shortcuts_combo_hover_border_hex}; }}
        """

    def shortcuts_sidebar_note_muted_stylesheet(self) -> str:
        return f"""
            QLabel {{
                color: {self.shortcuts_note_muted_hex};
                font-size: 10pt;
            }}
        """

    def shortcuts_gear_style_normal(self) -> str:
        t = self
        return (
            f"display:inline-block; text-decoration:none; cursor:pointer; border:1px solid {t.shortcuts_gear_border_hex}; "
            f"border-radius:3px; padding:2px; background-color:{t.shortcuts_gear_bg_hex}; vertical-align:middle; margin-left:4px;"
        )

    def shortcuts_gear_style_hover(self) -> str:
        t = self
        return (
            f"display:inline-block; text-decoration:none; cursor:pointer; border:1px solid {t.shortcuts_gear_border_hover_hex}; "
            f"border-radius:3px; padding:2px; background-color:{t.shortcuts_gear_bg_hover_hex}; vertical-align:middle; margin-left:4px;"
        )

    def information_sidebar_outer_stylesheet(self) -> str:
        return f"QWidget {{ background-color: {self.information_panel_bg_hex}; }}"

    def information_sidebar_textbrowser_stylesheet(self) -> str:
        t = self
        track = t.information_textbrowser_bg_hex
        return f"""
            QTextBrowser {{
                background-color: {track};
                border: none;
                color: {t.sidebar_text_color_hex};
                font-family: "Courier New", "Monaco", "Menlo";
                font-size: 12pt;
                font-weight: normal;
                padding: 0;
            }}
            {macos_scrollbar_for_surface(t, track)}
        """

    def information_link_tooltip_stylesheet(self) -> str:
        t = self
        return f"""
            QLabel {{ background-color: {t.information_link_tooltip_bg_hex}; color: {t.information_link_tooltip_fg_hex};
            border: 1px solid {t.information_link_tooltip_border_hex};
            border-radius: 4px; padding: 4px 8px; font-size: 11pt; }}
        """

    def right_sidebar_combined_stylesheet(self) -> str:
        return f"QWidget {{ background-color: {self.sidebar_background_color_hex}; }}"

    def right_sidebar_inner_splitter_stylesheet(self) -> str:
        t = self
        return f"""
            QSplitter {{
                background-color: {t.sidebar_background_color_hex};
            }}
            QSplitter::handle {{
                background-color: {t.chrome_border_hex};
                border: none;
            }}
            QSplitter::handle:vertical {{
                height: {t.view_border_width_px}px;
            }}
        """