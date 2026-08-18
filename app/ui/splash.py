from __future__ import annotations

import math
import os

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import QWidget


_WORDMARK_FONT_LOADED = False
_WORDMARK_FAMILY = "Microsoft YaHei UI"
_SPLASH_LOGO_PIXMAP = None


class _FixedClock:
    def __init__(self, elapsed: int) -> None:
        self._elapsed = elapsed

    def elapsed(self) -> int:
        return self._elapsed

    def restart(self) -> None:
        self._elapsed = 0


def _wordmark_family() -> str:
    """Resolve the bundled rounded font once the application exists."""
    global _WORDMARK_FONT_LOADED, _WORDMARK_FAMILY
    if not _WORDMARK_FONT_LOADED:
        _WORDMARK_FONT_LOADED = True
        font_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets",
            "fonts",
            "FZCuYuan-GBK.ttf",
        )
        if os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            families = (
                QFontDatabase.applicationFontFamilies(font_id)
                if font_id >= 0
                else []
            )
            if families:
                _WORDMARK_FAMILY = families[0]
    return _WORDMARK_FAMILY


def _splash_logo_pixmap() -> QPixmap:
    """Load the original big-M icon asset once for the splash overlay."""
    global _SPLASH_LOGO_PIXMAP
    if _SPLASH_LOGO_PIXMAP is None:
        logo_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets",
            "icons",
            "splash_logo.png",
        )
        pixmap = QPixmap(logo_path)
        _SPLASH_LOGO_PIXMAP = pixmap if not pixmap.isNull() else QPixmap()
    return _SPLASH_LOGO_PIXMAP


class SplashOverlay(QWidget):
    """Startup splash rendered entirely with QPainter.

    The animation keeps the Meemaw wordmark and music-note motif from the
    reference.  Letters slide in from the right one after another at the same
    fixed speed, then keep bouncing with a constant triangle-wave speed.  The
    big M is not treated as an obstacle, so there is no climbing motion.
    """

    finished = Signal()
    exit_snapshot = Signal(object)

    DESIGN_W = 960.0
    DESIGN_H = 720.0
    FADE_IN_MS = 320
    FADE_OUT_MS = 0
    BOUNCE_PERIOD_MS = 440
    BOUNCE_AMPLITUDE = 26.0
    FIRST_ENTRY_MS = 420
    ENTRY_STAGGER_MS = 230
    ENTRY_SLIDE_MS = 340
    ENTRY_OFFSET = 280.0
    ENTRY_HOP_HEIGHT = 84.0
    DURATION_MS = 2600

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent; border: none;")
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)
        self._running = False
        self.hide()

    def start(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self._clock.restart()
        self._timer.start()
        self._running = True
        self.show()
        self.raise_()
        self.update()

    def stop(self) -> None:
        self._timer.stop()
        self._running = False
        self.hide()

    def snapshot(self, elapsed_ms: int = None) -> QPixmap:
        """Render the current splash frame into a standalone pixmap."""
        if elapsed_ms is None:
            elapsed_ms = (
                int(self._clock.elapsed()) if self._running else self.DURATION_MS
            )
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        real_clock = self._clock
        self._clock = _FixedClock(elapsed_ms)
        try:
            self.render(pixmap)
        finally:
            self._clock = real_clock
        return pixmap

    def _on_tick(self) -> None:
        if not self._running:
            return
        elapsed = int(self._clock.elapsed())
        if elapsed >= self.DURATION_MS + self.FADE_OUT_MS:
            snapshot = self.snapshot(self.DURATION_MS)
            self.stop()
            self.finished.emit()
            self.exit_snapshot.emit(snapshot)
            return
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())

    def _bounce_ratio(self, elapsed: int) -> float:
        """Smooth cosine bounce progress shared by letters and background."""
        phase = elapsed % self.BOUNCE_PERIOD_MS
        t = phase / float(self.BOUNCE_PERIOD_MS)
        return 0.5 - 0.5 * math.cos(2.0 * math.pi * t)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w = float(self.width())
        h = float(self.height())
        if w <= 1.0 or h <= 1.0:
            painter.end()
            return

        elapsed = int(self._clock.elapsed()) if self._running else 0
        scale = min(w / self.DESIGN_W, h / self.DESIGN_H)
        offset_x = (w - self.DESIGN_W * scale) / 2.0
        offset_y = (h - self.DESIGN_H * scale) / 2.0

        painter.save()
        painter.translate(offset_x, offset_y)
        painter.scale(scale, scale)

        opacity = 1.0
        if elapsed < self.FADE_IN_MS:
            opacity = elapsed / float(self.FADE_IN_MS)
        tail = elapsed - self.DURATION_MS
        if tail > 0 and self.FADE_OUT_MS > 0:
            opacity *= max(0.0, 1.0 - tail / float(self.FADE_OUT_MS))
        painter.setOpacity(max(0.0, min(1.0, opacity)))

        self._draw_background(painter, elapsed)
        self._draw_waveforms(painter, elapsed)
        self._draw_notes(painter, elapsed)
        self._draw_logo(painter, elapsed)
        self._draw_vignette(painter)
        self._draw_wordmark(painter, elapsed)
        painter.restore()
        painter.end()

    def _draw_background(self, painter: QPainter, elapsed: int) -> None:
        rect = QRectF(0.0, 0.0, self.DESIGN_W, self.DESIGN_H)
        bg = QLinearGradient(rect.topLeft(), rect.bottomRight())
        bg.setColorAt(0.0, QColor(27, 4, 36))
        bg.setColorAt(0.3, QColor(31, 10, 52))
        bg.setColorAt(0.56, QColor(21, 15, 58))
        bg.setColorAt(0.78, QColor(9, 16, 46))
        bg.setColorAt(1.0, QColor(3, 8, 30))
        painter.fillRect(rect, bg)

        bounce = self._bounce_ratio(elapsed)
        pulse = 0.95 + 0.05 * bounce
        glows = (
            (480.0, 284.0, 275.0, QColor(150, 62, 190), 18),
            (140.0, 355.0, 260.0, QColor(175, 50, 135), 10),
            (765.0, 355.0, 285.0, QColor(48, 118, 195), 12),
            (90.0, 130.0, 240.0, QColor(140, 50, 125), 7),
        )
        for gx, gy, radius, color, alpha in glows:
            gy -= bounce * 8.0
            glow = QRadialGradient(QPointF(gx, gy), radius)
            top = QColor(color)
            top.setAlpha(int(alpha * pulse))
            mid = QColor(color)
            mid.setAlpha(int(alpha * 0.42))
            glow.setColorAt(0.0, top)
            glow.setColorAt(0.58, mid)
            glow.setColorAt(1.0, QColor(0, 0, 20, 0))
            painter.fillRect(rect, glow)

    def _draw_waveforms(self, painter: QPainter, elapsed: int) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        bar_w = 9.0
        gap = 11.0
        center_y = 350.0
        max_h = 260.0
        left_pattern = (
            0.85, 0.38, 0.55, 0.95, 0.42, 0.6, 0.88, 0.46, 0.68,
            0.3, 0.82, 0.4, 0.58, 0.92, 0.48, 0.7, 0.62,
        )
        right_pattern = (
            0.95, 0.5, 0.88, 0.42, 0.62, 0.85, 0.35, 0.55, 0.92,
            0.48, 0.75, 0.38, 0.9, 0.52, 0.72, 0.42, 0.6, 0.8,
            0.46, 0.68,
        )
        bounce = self._bounce_ratio(elapsed)
        wave = 1.0 + 0.06 * bounce
        for side in (-1, 1):
            x0 = 4.0 if side < 0 else 566.0
            pattern = left_pattern if side < 0 else right_pattern
            step = bar_w + gap
            band_w = len(pattern) * step - gap

            baseline = QColor(
                int(192 if side < 0 else 48),
                int(52 if side < 0 else 132),
                int(162 if side < 0 else 218),
                48,
            )
            painter.setBrush(baseline)
            painter.drawRoundedRect(
                QRectF(x0 - 5.0, center_y - 9.0, band_w + 10.0, 18.0),
                9.0,
                9.0,
            )
            glow = QColor(baseline)
            glow.setAlpha(13)
            painter.setBrush(glow)
            painter.drawRoundedRect(
                QRectF(x0 - 9.0, center_y - 15.0, band_w + 18.0, 30.0),
                15.0,
                15.0,
            )

            for i in range(len(pattern)):
                phase = 1.0 + 0.06 * math.sin((elapsed + i * 65.0) / 320.0)
                height = max_h * pattern[i] * wave * phase
                height = max(14.0, min(max_h, height))
                x = x0 + i * step
                y = center_y - height / 2.0
                mix = i / max(1, len(pattern) - 1.0)
                if side < 0:
                    r1, g1, b1 = 210, 30, 138
                    r2, g2, b2 = 185, 58, 188
                    hr, hg, hb = 255, 150, 218
                else:
                    r1, g1, b1 = 42, 110, 232
                    r2, g2, b2 = 86, 205, 245
                    hr, hg, hb = 150, 238, 255
                r = int(r1 + (r2 - r1) * mix)
                g = int(g1 + (g2 - g1) * mix)
                b = int(b1 + (b2 - b1) * mix)
                painter.setBrush(QColor(r, g, b, 14))
                painter.drawRoundedRect(
                    QRectF(x - 4.5, y - 4.5, bar_w + 9.0, height + 9.0),
                    (bar_w + 9.0) / 2.0,
                    (bar_w + 9.0) / 2.0,
                )
                painter.setBrush(QColor(r, g, b, 118 if side >= 0 else 90))
                painter.drawRoundedRect(
                    QRectF(x, y, bar_w, height),
                    bar_w / 2.0,
                    bar_w / 2.0,
                )
                painter.setBrush(
                    QColor(
                        hr,
                        hg,
                        hb,
                        70 if side >= 0 else 54,
                    )
                )
                painter.drawRoundedRect(
                    QRectF(x + 1.5, y + height * 0.16, bar_w - 3.0, height * 0.58),
                    (bar_w - 3.0) / 2.0,
                    (bar_w - 3.0) / 2.0,
                )

    def _draw_note_path(self, painter: QPainter, x: float, y: float, size: float) -> None:
        head_r = size * 0.34
        stem_w = size * 0.10
        path = QPainterPath()
        path.addEllipse(QPointF(x, y), head_r, head_r)
        path.addRoundedRect(
            QRectF(x + head_r * 0.72, y - size * 0.72, stem_w, size * 0.95),
            stem_w / 2.0,
            stem_w / 2.0,
        )
        flag = QPainterPath(QPointF(x + head_r * 0.72 + stem_w, y - size * 0.72))
        flag.cubicTo(
            x + head_r * 0.72 + stem_w * 5.5,
            y - size * 0.55,
            x + head_r * 0.72 + stem_w * 4.6,
            y - size * 0.12,
            x + head_r * 0.72 + stem_w * 6.8,
            y + size * 0.12,
        )
        flag.cubicTo(
            x + head_r * 0.72 + stem_w * 4.2,
            y + size * 0.10,
            x + head_r * 0.72 + stem_w * 3.0,
            y - size * 0.28,
            x + head_r * 0.72 + stem_w,
            y - size * 0.20,
        )
        flag.closeSubpath()
        path.addPath(flag)
        painter.drawPath(path)

    def _draw_notes(self, painter: QPainter, elapsed: int) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        positions = [
            (132.0, 168.0, 26.0, 0.0),
            (838.0, 142.0, 24.0, 90.0),
            (128.0, 560.0, 22.0, 160.0),
            (838.0, 520.0, 26.0, 220.0),
            (92.0, 360.0, 18.0, 50.0),
            (852.0, 300.0, 19.0, 140.0),
            (220.0, 96.0, 17.0, 280.0),
            (742.0, 84.0, 20.0, 320.0),
            (76.0, 210.0, 15.0, 40.0),
            (880.0, 210.0, 16.0, 180.0),
            (196.0, 452.0, 18.0, 240.0),
            (780.0, 468.0, 18.0, 300.0),
            (36.0, 118.0, 13.0, 60.0),
            (914.0, 108.0, 14.0, 200.0),
            (62.0, 600.0, 14.0, 120.0),
            (900.0, 590.0, 15.0, 260.0),
            (300.0, 500.0, 13.0, 340.0),
            (640.0, 500.0, 14.0, 80.0),
        ]
        for x, y, size, phase in positions:
            bob = math.sin((elapsed + phase) / 150.0) * 5.0
            painter.setBrush(QColor(238, 238, 250, 80))
            self._draw_note_path(painter, x, y + bob, size)

        particles = (
            (44.0, 92.0), (188.0, 74.0), (300.0, 128.0), (628.0, 96.0),
            (742.0, 150.0), (912.0, 118.0), (72.0, 490.0), (210.0, 522.0),
            (306.0, 448.0), (620.0, 500.0), (760.0, 470.0), (912.0, 486.0),
            (112.0, 372.0), (268.0, 376.0), (700.0, 376.0), (856.0, 360.0),
            (90.0, 286.0), (760.0, 258.0), (176.0, 642.0), (384.0, 620.0),
            (560.0, 626.0), (760.0, 650.0), (896.0, 642.0), (52.0, 626.0),
            (404.0, 140.0), (516.0, 128.0), (700.0, 620.0), (280.0, 120.0),
            (884.0, 220.0), (66.0, 210.0),
        )
        for index, (x, y) in enumerate(particles):
            radius = 1.2 + (index % 4) * 0.55
            drift = math.sin((elapsed + index * 47.0) / 210.0) * 3.0
            alpha = 18 + (index * 13) % 30
            red = 150 + (index * 23) % 80
            green = 120 + (index * 37) % 95
            painter.setBrush(QColor(red, green, 255, alpha))
            painter.drawEllipse(QPointF(x + drift, y), radius, radius)

    def _draw_logo(self, painter: QPainter, elapsed: int) -> None:
        center_x = 489.0
        center_y = 332.0
        appear = min(1.0, elapsed / 190.0)
        bounce = self._bounce_ratio(elapsed)
        pulse = 1.0 + 0.03 * bounce
        floor = QRadialGradient(QPointF(center_x, center_y), 235.0)
        floor.setColorAt(0.0, QColor(196, 92, 224, int(38 * appear)))
        floor.setColorAt(0.55, QColor(110, 110, 210, 20))
        floor.setColorAt(1.0, QColor(0, 0, 40, 0))
        painter.fillRect(
            QRectF(center_x - 250.0, center_y - 250.0, 500.0, 500.0),
            floor,
        )

        logo = _splash_logo_pixmap()
        if logo.isNull():
            self._draw_logo_fallback(painter, appear, pulse)
            return

        anim_scale = (0.96 + 0.04 * appear) * pulse
        target_h = 312.0
        target_w = target_h * logo.width() / logo.height()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.translate(center_x, center_y)
        painter.scale(anim_scale, anim_scale)
        painter.setOpacity(painter.opacity() * appear)
        painter.drawPixmap(
            QRectF(-target_w / 2.0, -target_h / 2.0, target_w, target_h),
            logo,
            QRectF(0.0, 0.0, float(logo.width()), float(logo.height())),
        )
        painter.restore()

    def _draw_logo_fallback(
        self, painter: QPainter, appear: float, pulse: float
    ) -> None:
        """Keep the old painter version available if the icon asset is absent."""
        (
            body_path,
            board_path,
            left_dot_path,
            right_dot_path,
        ) = self._build_note_m_path(appear, pulse)

        board_gradient = QLinearGradient(
            board_path.boundingRect().topLeft(),
            board_path.boundingRect().bottomRight(),
        )
        board_gradient.setColorAt(0.0, QColor(255, 128, 214))
        board_gradient.setColorAt(0.45, QColor(196, 106, 240))
        board_gradient.setColorAt(0.78, QColor(122, 120, 250))
        board_gradient.setColorAt(1.0, QColor(78, 190, 250))
        painter.setOpacity(painter.opacity() * appear)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(board_gradient)
        painter.drawPath(board_path)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(
                QColor(255, 255, 255, 92),
                max(2.0, 5.0 * appear),
            )
        )
        painter.drawPath(board_path)

        body = QLinearGradient(
            body_path.boundingRect().topLeft(),
            body_path.boundingRect().bottomRight(),
        )
        body.setColorAt(0.0, QColor(255, 94, 214))
        body.setColorAt(0.38, QColor(235, 76, 228))
        body.setColorAt(0.68, QColor(148, 92, 250))
        body.setColorAt(1.0, QColor(70, 190, 250))
        painter.setPen(QPen(QColor(255, 255, 255, 58), 1.6))
        painter.setBrush(body)
        painter.drawPath(body_path)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 48), 3.2))
        painter.drawPath(body_path)

        painter.setPen(QPen(QColor(255, 255, 255, 90), 2.0))
        painter.setBrush(QColor(255, 118, 196))
        painter.drawPath(left_dot_path)
        painter.setBrush(QColor(72, 190, 250))
        painter.drawPath(right_dot_path)

    def _build_note_m_path(
        self, appear: float, pulse: float
    ) -> tuple[QPainterPath, QPainterPath]:
        """Build the icon glyph and its rounded-square board with QPainter."""
        # Continuous music-note M: two vertical stems curving into the centre
        # dip, exactly like the app icon (no heart and no star).
        stroke = QPainterPath()
        stroke.moveTo(-95.0, -88.0)
        stroke.lineTo(-95.0, 50.0)
        stroke.cubicTo(-95.0, 52.0, -34.0, 50.0, 0.0, 57.0)
        stroke.cubicTo(34.0, 50.0, 95.0, 52.0, 95.0, 50.0)
        stroke.lineTo(95.0, -88.0)

        stroker = QPainterPathStroker()
        stroker.setWidth(35.0)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        body = stroker.createStroke(stroke)

        # Two note dots under the outer stems, mirroring the icon. They are
        # kept separate so the left one can stay pink and the right one blue.
        left_dot = QPainterPath()
        left_dot.addEllipse(QPointF(-81.0, 82.0), 14.0, 12.0)
        right_dot = QPainterPath()
        right_dot.addEllipse(QPointF(81.0, 86.0), 16.0, 13.5)

        # Rounded-square board sized around the glyph with an icon-like
        # margin (a little wider than tall).
        board = QPainterPath()
        board.addRoundedRect(
            QRectF(-138.0, -130.0, 276.0, 252.0),
            56.0,
            56.0,
        )

        scale = min(306.0 / 276.0, 300.0 / 252.0)
        scale *= (0.96 + 0.04 * appear) * pulse
        transform = QTransform()
        # Center both shapes around the logo position.
        transform.translate(
            self.DESIGN_W / 2.0,
            332.0,
        )
        transform.scale(scale, scale)
        return (
            transform.map(body),
            transform.map(board),
            transform.map(left_dot),
            transform.map(right_dot),
        )

    def _draw_vignette(self, painter: QPainter) -> None:
        rect = QRectF(0.0, 0.0, self.DESIGN_W, self.DESIGN_H)
        vignette = QRadialGradient(QPointF(480.0, 360.0), 580.0)
        vignette.setColorAt(0.0, QColor(0, 0, 0, 0))
        vignette.setColorAt(0.7, QColor(0, 0, 0, 0))
        vignette.setColorAt(1.0, QColor(0, 0, 12, 170))
        painter.fillRect(rect, vignette)

    def _letter_centers(self) -> list[float]:
        return [256.0, 351.0, 427.5, 525.5, 620.0, 714.0]

    def _letter_sizes(self) -> list[float]:
        return [84.0, 101.0, 99.0, 98.0, 95.0, 102.0]

    def _draw_wordmark(self, painter: QPainter, elapsed: int) -> None:
        center_x = self.DESIGN_W / 2.0
        baseline = 566.0
        letters = ["M", "e", "e", "m", "a", "w"]
        sizes = self._letter_sizes()
        centers = self._letter_centers()

        for index, (letter, size, center) in enumerate(
            zip(letters, sizes, centers)
        ):
            start_ms = self.FIRST_ENTRY_MS + index * self.ENTRY_STAGGER_MS
            if elapsed < start_ms:
                continue
            slide_ms = elapsed - start_ms
            slide_t = min(1.0, slide_ms / float(self.ENTRY_SLIDE_MS))
            # Jump entry: constant-speed horizontal travel plus a hop arc.
            x_shift = self.ENTRY_OFFSET * (1.0 - slide_t)
            hop = math.sin(math.pi * slide_t)
            y_shift = -self.ENTRY_HOP_HEIGHT * hop

            if slide_t >= 1.0:
                # Cosine wave gives every letter a soft, continuous bounce.
                lift = self._bounce_ratio(elapsed + index * 40)
                y_shift = -self.BOUNCE_AMPLITUDE * lift
            letter_alpha = 0.35 + 0.65 * slide_t

            font = QFont(_wordmark_family(), int(size), QFont.Weight.Bold)
            painter.setFont(font)
            path = QPainterPath()
            path.addText(QPointF(0, 0), font, letter)
            bounds = path.boundingRect()
            x = center + x_shift - bounds.center().x()
            y = baseline + y_shift - bounds.bottom()
            path.translate(x, y)

            painter.save()
            painter.setOpacity(painter.opacity() * letter_alpha)
            glow_color = QColor(142, 208, 255)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for width, alpha in (
                (3.0, 55),
                (7.0, 42),
                (12.0, 30),
                (18.0, 20),
                (26.0, 12),
                (36.0, 6),
            ):
                glow = QColor(glow_color)
                glow.setAlpha(alpha)
                painter.setPen(QPen(glow, width))
                painter.drawPath(path)

            core = QLinearGradient(0.0, y, 0.0, y + bounds.height())
            core.setColorAt(0.0, QColor(255, 255, 255, 255))
            core.setColorAt(1.0, QColor(238, 246, 255, 255))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(core)
            painter.drawPath(path)

            reflected = QTransform(1.0, 0.0, 0.0, -1.0, 0.0, 2.0 * baseline).map(
                path
            )
            fade = QLinearGradient(
                0.0, baseline, 0.0, baseline + bounds.height() * 0.9
            )
            fade.setColorAt(0.0, QColor(255, 255, 255, 110))
            fade.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(fade)
            painter.drawPath(reflected)
            painter.restore()
