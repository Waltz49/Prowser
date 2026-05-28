#!/usr/bin/env python3
"""
Status Notification Widget with stacked notification bubbles and animated layout.
Multiple notifications stack vertically; new ones slide existing bubbles up,
and timeouts slide remaining bubbles down to fill the gap.
"""

from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, QSize, QPoint,
    Signal, QParallelAnimationGroup,
)
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QFontMetrics
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from status_bar_config import StatusBarManager
from thumbnail_constants import TEXT_COLOR, TEXT_COLOR_HEX

BUBBLE_GAP = 6
SLIDE_DURATION_MS = 1500
FADE_IN_DURATION_MS = 250
FADE_OUT_DURATION_MS = 2000
MAX_BUBBLE_WIDTH = 420


class NotificationBubble(QWidget):
    """Top-level notification window. Uses setText + windowOpacity so whole element fades as one."""

    expired = Signal(object)
    dismissed = Signal(object)

    def __init__(self, message: str, parent_window=None):
        super().__init__(None)
        self.parent_window = parent_window
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setFocusPolicy(Qt.NoFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(False)
        self.label.setStyleSheet(f"""
            QLabel {{
                font-size: 12pt; background-color: #cacaca;
                border: 1px solid #4a4a4a; color: #2a2a2a;
                padding: 7px 10px; border-radius: 5px;
                max-width: {MAX_BUBBLE_WIDTH}px;
            }}
        """)
        layout.addWidget(self.label)
        self.label.setText(message)
        self.adjustSize()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._on_timer_fired)
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._fade_anim.finished.connect(self._on_fade_finished)
        self._hiding = False

    def _on_timer_fired(self):
        self.expired.emit(self)

    def start_show(self, duration: int):
        self._hiding = False
        self.setWindowOpacity(0.0)
        self._fade_anim.stop()
        self._fade_anim.setDuration(FADE_IN_DURATION_MS)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(0.9)
        QTimer.singleShot(0, self._fade_anim.start)
        self._hide_timer.start(duration)

    def is_still_displayed(self) -> bool:
        """True if visible and not in fade-out (still the active toast)."""
        return self.isVisible() and not self._hiding

    def start_fade_out(self):
        if self._hiding:
            return
        self._hiding = True
        self._hide_timer.stop()
        self._fade_anim.stop()
        self.setWindowOpacity(0.9)
        self._fade_anim.setDuration(FADE_OUT_DURATION_MS)
        self._fade_anim.setStartValue(0.9)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def _on_fade_finished(self):
        if self._hiding and self.windowOpacity() <= 0.01:
            self.dismissed.emit(self)

    def enterEvent(self, event):
        self._hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._hiding:
            self._hide_timer.start(1000)
        super().leaveEvent(event)


class DisappearingTabNotification(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self._init_height = 0
        self._shown = False

        self.text = ""
        self.bg_color = QColor(StatusBarManager.STATUS_BG_COLOR if hasattr(StatusBarManager, "STATUS_BG_COLOR") else "#232a32")
        self.text_color = TEXT_COLOR
        self.font = QFont('Segoe UI', 10, QFont.Bold)

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet(f"color: {TEXT_COLOR_HEX}; background: transparent; font-weight:600;")
        self.label.setFont(self.font)
        self.label.setWordWrap(False)
        self.label.setText("")
        self._resized = False

        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self._start_fade_out)

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(2000)
        self._fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._fade_anim.finished.connect(self._after_fade_out)

    def _start_fade_out(self):
        self._fade_anim.stop()
        self._fade_anim.setDuration(1700)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def _after_fade_out(self):
        self.setVisible(False)
        self._shown = False
        self.setWindowOpacity(1.0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        rect_full = self.rect()
        radius = 11
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.bg_color)
        painter.drawRoundedRect(0, 0, rect_full.width(), rect_full.height(), radius, radius)
        if self.text:
            painter.setFont(self.font)
            painter.setPen(TEXT_COLOR)
            text_rect = QRect(0, 0, rect_full.width(), rect_full.height())
            painter.drawText(text_rect, int(Qt.AlignCenter | Qt.TextWordWrap), self.text)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if not self._resized:
            self.label.setFixedSize(self.size())
            self._resized = True


class StatusNotification(QWidget):
    """Manages stacked top-level notification bubbles with animated layout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self._bubbles = []
        self._pos_anim_group = None
        self.setup_ui()

    def setup_ui(self):
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.hide()

    def _measure_bubble_size(self, message: str):
        """Create a bubble off-screen to measure its size before adding to stack."""
        bubble = NotificationBubble(message, self.parent_window)
        bubble.adjustSize()
        w, h = bubble.width(), bubble.height()
        bubble.deleteLater()
        return w, h

    def _get_screen_origin(self):
        """(x, base_y) in screen coords: left edge and Y of bottom of stack."""
        if not self.parent_window:
            return 20, 100
        parent_rect = self.parent_window.frameGeometry()
        status_bar_height = 0
        if hasattr(self.parent_window, "status_bar"):
            sb = getattr(self.parent_window, "status_bar")
            if sb and sb.isVisible():
                status_bar_height = sb.height() or (sb.sizeHint().height() if hasattr(sb, "sizeHint") else 0)
        base_y = parent_rect.y() + parent_rect.height() - status_bar_height
        base_y = max(parent_rect.y() + 12, base_y)
        return parent_rect.x(), base_y

    def _position_bubbles(self, bubbles, base_y):
        """Position bubbles in screen coords. Oldest at top, newest at bottom."""
        x, _ = self._get_screen_origin()
        y = base_y
        for b in reversed(bubbles):
            y -= b.height()
            b.move(x, y)
            y -= BUBBLE_GAP

    def _layout_all_bubbles(self):
        """Position all bubbles. Bottom stays anchored to status bar."""
        if not self._bubbles:
            return
        _, base_y = self._get_screen_origin()
        self._position_bubbles(self._bubbles, base_y)
        for b in self._bubbles:
            b.raise_()

    def show_message(self, message: str, duration: int = 3000):
        if self._bubbles:
            last = self._bubbles[-1]
            if last.label.text() == message and last.is_still_displayed():
                return
        w, new_h = self._measure_bubble_size(message)
        bubble = NotificationBubble(message, self.parent_window)
        bubble.adjustSize()
        bubble.expired.connect(self._on_bubble_expired)
        bubble.dismissed.connect(self._on_bubble_dismissed)

        if not self._bubbles:
            self._bubbles.append(bubble)
            self._layout_all_bubbles()
            bubble.show()
            bubble.raise_()
            if self.parent_window:
                self.parent_window.activateWindow()
                self.parent_window.raise_()
                QTimer.singleShot(50, self._restore_focus_to_parent)
            bubble.start_show(duration)
            return

        # Animate existing bubbles up, then add new one at bottom
        _, base_y = self._get_screen_origin()
        delta = new_h + BUBBLE_GAP
        new_base_y = base_y - delta

        from PySide6.QtCore import QVariantAnimation
        anim = QVariantAnimation(self)
        anim.setDuration(SLIDE_DURATION_MS)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(base_y)
        anim.setEndValue(new_base_y)

        def on_val_changed(val):
            if isinstance(val, (int, float)):
                self._position_bubbles(self._bubbles, int(val))

        def on_finished():
            self._bubbles.append(bubble)
            self._layout_all_bubbles()
            bubble.show()
            bubble.raise_()
            bubble.start_show(duration)

        anim.valueChanged.connect(on_val_changed)
        anim.finished.connect(on_finished)
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def _on_bubble_expired(self, bubble):
        """Timer fired: all bubbles fade out. Overlap with moving items is OK."""
        try:
            self._bubbles.index(bubble)
        except ValueError:
            return
        bubble.start_fade_out()

    def _remove_bubble_immediately(self, bubble, idx):
        """Remove bubble without fade. Items above move down to fill gap; items below never move."""
        removed_h = bubble.height() + (BUBBLE_GAP if idx < len(self._bubbles) - 1 else 0)
        self._bubbles.pop(idx)
        bubble.close()
        bubble.deleteLater()

        if not self._bubbles:
            return

        _, base_y = self._get_screen_origin()

        # Bubbles below stay put. Animate bubbles above removed one down.
        to_animate = self._bubbles[:idx]
        if to_animate:
            if self._pos_anim_group:
                self._pos_anim_group.stop()
                self._pos_anim_group = None
            group = QParallelAnimationGroup(self)
            for b in to_animate:
                anim = QPropertyAnimation(b, b"pos")
                anim.setDuration(SLIDE_DURATION_MS)
                anim.setEasingCurve(QEasingCurve.OutCubic)
                target_y = b.y() + removed_h
                anim.setStartValue(b.pos())
                anim.setEndValue(QPoint(b.x(), target_y))
                group.addAnimation(anim)

            def after_slide():
                self._pos_anim_group = None
                self._layout_all_bubbles()

            group.finished.connect(after_slide)
            self._pos_anim_group = group
            group.start(QPropertyAnimation.DeleteWhenStopped)
        else:
            self._layout_all_bubbles()

    def _on_bubble_dismissed(self, bubble):
        """Fade-out completed; remove bubble and animate only items above it down. Items below stay put."""
        try:
            idx = self._bubbles.index(bubble)
        except ValueError:
            return
        self._bubbles.pop(idx)
        if self._pos_anim_group:
            self._pos_anim_group.stop()
            self._pos_anim_group = None
        bubble.close()
        bubble.deleteLater()

        if not self._bubbles:
            return

        _, base_y = self._get_screen_origin()
        removed_h = bubble.height() + BUBBLE_GAP
        to_animate = self._bubbles[:idx]
        if to_animate:
            group = QParallelAnimationGroup(self)
            for b in to_animate:
                anim = QPropertyAnimation(b, b"pos")
                anim.setDuration(SLIDE_DURATION_MS)
                anim.setEasingCurve(QEasingCurve.OutCubic)
                target_y = b.y() + removed_h
                anim.setStartValue(b.pos())
                anim.setEndValue(QPoint(b.x(), target_y))
                group.addAnimation(anim)

            def after_slide():
                self._pos_anim_group = None
                self._layout_all_bubbles()

            group.finished.connect(after_slide)
            self._pos_anim_group = group
            group.start(QPropertyAnimation.DeleteWhenStopped)
        else:
            self._layout_all_bubbles()

    def _restore_focus_to_parent(self):
        if not self.parent_window:
            return
        self.clearFocus()
        mw = self.parent_window
        mw.activateWindow()
        if hasattr(mw, 'main_content_widget') and mw.main_content_widget:
            mw.main_content_widget.setFocus(Qt.OtherFocusReason)

    def show_error_message(self, message: str, duration: int = 5000):
        """Show an error notification (longer default duration)."""
        self.show_message(message, duration)
