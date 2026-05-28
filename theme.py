"""Shared Qt stylesheet builders for light/dark theme palettes."""

from __future__ import annotations

from PySide6.QtGui import QColor

from theme_base import asset_url


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
        background-color: {t.default_background_color_hex};
    }}
    QMenu {{
        background-color: {t.context_menu_bg_hex};
        color: {t.text_color_hex};
        border: 1px solid {t.border_default_hex};
    }}
    QMenu::item {{
            min-height: 20px;
            font-size: 13pt;
            font-weight: 500;
            color: {t.text_color_hex};
            padding:0px 8px
        }}
    QMenu::item:selected {{
        background-color: {t.widget_bg_hover_hex};
    }}
    QMenu::item:disabled {{
        color: {t.qmenu_item_disabled_hex};
        font-weight: 100;
    }}
    QMenu::separator {{
        height: 1px;
        background: {t.text_disabled_hex};
        margin: 5px 8px;
    }}

    QStatusBar {{
        background-color: {t.dialog_background_hex};
        color: {t.dialog_text_color_hex};
        border-top: {t.view_border_width_px}px solid {t.chrome_border_hex};
    }}

    QLabel {{
        color: {t.dialog_text_color_hex};
        background: transparent;
        background-color: transparent;
    }}

    QPushButton {{
        background-color: {t.button_bg_default_hex};
        color: {t.button_text_default_hex};
        border: 1px solid {t.button_border_default_hex};
        border-radius: 5px;
        padding: 6px 18px;
        min-width: 100px;
        font-size: 13px;
        font-family: 'Arial Narrow', Arial;
        letter-spacing: 0.5px;
    }}
    QPushButton:default {{
        background-color: {t.button_default_bg_hex};
        color: #ffffff;
        border: 1px solid {t.button_default_border_hex};
    }}
    QPushButton:hover {{
        background-color: {t.button_bg_hover_hex};
        color: {t.button_text_hover_hex};
        border: 1px solid {t.button_border_hover_hex};
    }}
    QPushButton:focus {{
        background-color: {t.current_image_background_color_hex};
        color: #ffffff;
        border: {t.current_image_border_width_index}px solid {t.current_image_border_color_hex};
        outline: none;
    }}
    QPushButton:pressed {{
        background-color: {t.button_bg_pressed_hex};
        color: {t.dialog_text_color_hex};
    }}
    QPushButton:disabled {{
        background-color: {t.widget_bg_disabled_hex};
        color: {t.text_disabled_hex};
        border-color: {t.border_default_hex};
    }}
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

    QSpinBox {{
        font-size: 12px;
        border: 2px solid {t.border_default_hex};
        padding: 5px;
        margin-left: 10px;
        border-radius: 4px;
        background-color: transparent;
        text-align: right;
    }}
    QSpinBox:focus {{
        border: 2px solid {t.accent_color_hex};
    }}

    QSpinBox:pressed {{
        border: 2px solid {t.accent_color_hex};
    }}
    QSpinBox:disabled {{
        border: 2px solid {t.widget_bg_disabled_hex};
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        height: 25px;
        width: 25px;
        top:-4px;
        left: 6px;
        height: 16px;
        width: 18px;
        top:0px;
    }}
    QSpinBox::down-button {{ top: 2px; }}

    QSpinBox:disabled {{
        background-color: {t.dialog_background_hex};
        color: {t.spinbox_disabled_text_hex};
        border-color: {t.spinbox_disabled_border_hex};
    }}

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
        background-color: {t.default_background_color_hex};
    }}
    QMenu {{
        background-color: {t.context_menu_bg_hex};
        color: {t.text_color_hex};
        border: 1px solid {t.border_default_hex};
    }}
    QMenu::item {{
            min-height: 20px;
            font-size: 13pt;
            font-weight: 500;
            color:{t.text_color_hex};
            padding:0px 8px
        }}
    QMenu::item:selected {{
        background-color: {t.widget_bg_hover_hex};
    }}
    QMenu::item:disabled {{
        color: {t.qmenu_item_disabled_hex};
        font-weight: 100;
    }}
    QMenu::separator {{
        height: 1px;
        background: {t.text_disabled_hex};
        margin: 5px 8px;
    }}

    /* Status Bar */
    QStatusBar {{
        background-color: {t.dialog_background_hex};
        color: {t.dialog_text_color_hex};
        border-top: {t.view_border_width_px}px solid {t.chrome_border_hex};
    }}

    /* Labels */
    QLabel {{
        color: {t.dialog_text_color_hex};
        background: transparent;
        background-color: transparent;
    }}

    /* Buttons */
    QPushButton {{
        background-color: {t.button_bg_default_hex};
        color: {t.button_focus_text_hex};
        border: 1px solid {t.button_border_default_hex};
        border-radius: 5px;
        padding: 6px 18px;
        min-width: 100px;
        font-size: 13px;
        font-family: 'Arial Narrow', Arial;
        letter-spacing: 0.5px;
    }}
    QPushButton:default {{
        background-color: {t.button_default_bg_hex};
        color: {t.button_focus_text_hex};
        border: 1px solid {t.button_default_border_hex};
    }}
    QPushButton:hover {{
        background-color: {t.button_bg_hover_hex};
        color: {t.button_text_hover_hex};
        border: 1px solid {t.button_border_hover_hex};
    }}
    QPushButton:focus {{
        background-color: {t.current_image_background_color_hex};
        color: {t.dialog_text_color_hex};
        border: {t.current_image_border_width_index}px solid {t.current_image_border_color_hex};
        outline: none;
    }}
    QPushButton:pressed {{
        background-color: {t.button_bg_pressed_hex};
        color: {t.dialog_text_color_hex};
    }}
    QPushButton:disabled {{
        background-color: {t.widget_bg_disabled_hex};
        color: {t.text_disabled_hex};
        border-color: {t.dialog_background_hex};
    }}
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


    /* Spin Box */
    QSpinBox {{
        font-size: 12px;
        border: 2px solid {t.border_default_hex};
        padding: 5px;
        margin-left: 10px;
        border-radius: 4px;
        background-color: transparent;
        text-align: right;
    }}
    QSpinBox:focus {{
        border: 2px solid {t.accent_color_hex};
    }}

    QSpinBox:pressed {{
        border: 2px solid {t.accent_color_hex};
    }}
    QSpinBox:disabled {{
        border: 2px solid {t.widget_bg_disabled_hex};
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        height: 25px;
        width: 25px;
        top:-4px;
        left: 6px;
        height: 16px;
        width: 18px;
        top:0px;
    }}
    QSpinBox::down-button {{ top: 2px; }}

    QSpinBox:disabled {{
        background-color: {t.dialog_background_hex};
        color: {t.spinbox_disabled_text_hex};
        border-color: {t.spinbox_disabled_border_hex};
    }}

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
    """.strip()

class ThemeStylesMixin:
    """Stylesheet methods shared by LightTheme and DarkTheme (palette via `self`)."""

    def qmenu_stylesheet(self) -> str:
        t = self
        return f"""
    QMenu {{
        background-color: {t.context_menu_bg_hex};
        color: {t.text_color_hex};
        border: 1px solid {t.border_default_hex};
        border-radius: 7px;
        padding-top: 7px;
        padding-bottom: 7px;
    }}
    QMenu::separator {{
        height: 1px;
        background: {t.text_disabled_hex};
        margin: 5px 8px
    }}
    QMenu::item {{
        min-height: 20px;
        font-size: 13pt;
        font-weight: 500;
        color: {t.text_color_hex};
        padding:0px 8px
    }}
    QMenu::item:selected {{ background-color: {t.widget_bg_hover_hex}; }}
    QMenu::item:disabled {{color: {t.qmenu_item_disabled_hex}; font-weight: 100;}}
    """

    def heading_color_hex(self) -> str:
        if self.theme_id == "light":
            return QColor(self.text_color_hex).darker(108).name()
        return QColor(self.text_color_hex).lighter(115).name()

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

    def status_bar_context_menu_stylesheet(self) -> str:
        t = self
        return f"""
            QMenu {{
                background-color: {t.context_menu_bg_hex};
                color: {t.text_color_hex};
                border-top: 1px solid {t.status_menu_border_hex};
                border-left: 1px solid {t.status_menu_border_hex};
                border-right: 1px solid {t.status_menu_border_hex};
                border-bottom: 0px solid {t.status_menu_border_hex};
                padding: 2px;
            }}
            QMenu::item {{
                background-color: transparent;
                padding: 4px 20px 4px 20px;
                font-size: 13px;
                color: {t.text_color_hex};
            }}
            QMenu::item:selected {{
                background-color: {t.status_menu_selected_hex};
            }}
            QMenu::item:disabled {{
                color: {t.status_menu_grayed_hex};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {t.text_disabled_hex};
                margin-left: 10px;
                margin-right: 10px;
                margin-top: 4px;
                margin-bottom: 4px;
            }}
        """

    def file_tree_panel_stylesheet(self) -> str:
        """Embedded file tree (left sidebar) — distinct from generic QTreeView in global sheet."""
        t = self
        fw = "normal" if self.theme_id == "light" else "100"
        tc = t.dialog_text_color_hex
        return f"""
            QTreeView {{
                background-color: {t.default_background_color_hex};
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
                background-color: {t.default_background_color_hex};
            }}
            QTreeView::item:selected {{
                background-color: {t.tree_view_selection_bg_hex};
                color: {tc};
            }}
            QTreeView::item[highlighted="true"] {{
                background-color: {t.file_tree_item_highlighted_bg_hex};
                color: {tc};
                font-weight: bold;
            }}
            QTreeView::item[highlighted="true"]:selected {{
                background-color: {t.file_tree_item_highlighted_selected_bg_hex};
                color: {tc};
                font-weight: bold;
            }}
            QTreeView::item:hover {{
                background-color: {t.tree_view_item_hover_hex};
            }}
            QHeaderView::section {{
                background-color: {t.tree_header_section_bg_hex};
                color: {tc};
                padding: 2px 4px;
                border: 1px solid {t.tree_view_border_hex};
                font-weight: bold;
            }}
        """

    def file_tree_nav_container_stylesheet(self) -> str:
        return f"""
            background-color: {self.file_tree_nav_container_bg_hex};
            border-radius: 4px;
        """

    def file_tree_nav_icon_button_stylesheet(
        self, focus_bg: str, focus_border: str, focus_text: str, *, dim: bool = False
    ) -> str:
        t = self
        fg = t.file_tree_nav_button_text_dim_hex if dim else t.file_tree_nav_button_text_hex
        return f"""
            QPushButton {{
                background-color: {t.file_tree_nav_button_bg_hex};
                color: {fg};
                border: 1px solid {t.file_tree_nav_button_border_hex};
                border-radius: 3px;
                padding: 2px;
                font-size: 12px;
                min-width: 0px;
            }}
            QPushButton:hover {{ background-color: {t.file_tree_nav_button_hover_hex}; }}
            QPushButton:pressed {{ background-color: {t.file_tree_nav_button_pressed_hex}; }}
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
                color: {t.text_color_hex};
                font-size: 12px;
                padding: 2px 5px;
                background-color: {t.file_tree_dir_label_bg_hex};
                border: 1px solid {t.file_tree_dir_label_border_hex};
                border-radius: 3px;
            }}
        """

    def file_tree_filter_mode_button_stylesheet(self, size: int) -> str:
        t = self
        s = size
        icon_c = "#1a1a1a" if self.theme_id == "light" else "#ffffff"
        return f"""
            QPushButton {{
                background-color: {t.file_tree_filter_btn_bg_hex};
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
                background-color: {t.file_tree_filter_btn_bg_hex};
                border-color: {t.file_tree_filter_btn_border_hex};
            }}
            QPushButton:hover {{
                background-color: {t.file_tree_filter_btn_hover_hex};
            }}
            QPushButton:checked:hover {{
                background-color: {t.file_tree_filter_btn_hover_hex};
            }}
        """

    def file_tree_filter_separator_stylesheet(self) -> str:
        return f"QFrame {{ background-color: {self.file_tree_filter_sep_hex}; max-width: 1px; }}"

    def shortcuts_sidebar_widget_stylesheet(self) -> str:
        return f"QWidget {{ background-color: {self.shortcuts_panel_bg_hex}; }}"

    def shortcuts_sidebar_scroll_stylesheet(self) -> str:
        return f"""
            QScrollArea {{
                background-color: {self.shortcuts_scroll_bg_hex};
                border: none;
            }}
        """

    def shortcuts_sidebar_combo_stylesheet(self) -> str:
        t = self
        return f"""
            QComboBox {{
                color: {t.text_color_hex};
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
        return f"""
            QTextBrowser {{
                background-color: {t.information_textbrowser_bg_hex};
                border: none;
                color: {t.text_color_hex};
                font-family: "Courier New", "Monaco", "Menlo";
                font-size: 12pt;
                font-weight: normal;
                padding: 15px 18px;
            }}
        """

    def information_link_tooltip_stylesheet(self) -> str:
        t = self
        return f"""
            QLabel {{ background-color: {t.information_link_tooltip_bg_hex}; color: {t.information_link_tooltip_fg_hex};
            border: 1px solid {t.information_link_tooltip_border_hex};
            border-radius: 4px; padding: 4px 8px; font-size: 11pt; }}
        """

    def right_sidebar_combined_stylesheet(self) -> str:
        return f"QWidget {{ background-color: {self.right_sidebar_combined_bg_hex}; }}"

    def right_sidebar_inner_splitter_stylesheet(self) -> str:
        t = self
        return f"""
            QSplitter::handle {{
                background-color: {t.chrome_border_hex};
                border: none;
            }}
            QSplitter::handle:vertical {{
                height: {t.view_border_width_px}px;
            }}
        """