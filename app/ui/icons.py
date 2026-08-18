from __future__ import annotations

import os

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QPushButton

ACCENT = QColor("#ec4141")
WHITE = QColor("#ffffff")
_IMAGE_CACHE: dict[str, QPixmap] = {}


def _load_pixmap(path: str) -> QPixmap | None:
    if not path:
        return None
    pixmap = _IMAGE_CACHE.get(path)
    if pixmap is None:
        pixmap = QPixmap(path) if os.path.exists(path) else QPixmap()
        _IMAGE_CACHE[path] = pixmap
    return pixmap if not pixmap.isNull() else None


def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, float(t)))
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def _pen(color: QColor, width: float = 2.0) -> QPen:
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _draw_play(p: QPainter, r: QRectF, color: QColor) -> None:
    path = QPainterPath()
    left = r.left() + r.width() * 0.34
    right = r.left() + r.width() * 0.88
    top = r.top() + r.height() * 0.18
    bottom = r.top() + r.height() * 0.82
    path.moveTo(left, top)
    path.lineTo(right, r.center().y())
    path.lineTo(left, bottom)
    path.closeSubpath()
    p.fillPath(path, color)


def _draw_pause(p: QPainter, r: QRectF, color: QColor) -> None:
    bar_w = r.width() * 0.17
    radius = r.width() * 0.09
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(
        QRectF(
            r.left() + r.width() * 0.27,
            r.top() + r.height() * 0.2,
            bar_w,
            r.height() * 0.6,
        ),
        radius,
        radius,
    )
    p.drawRoundedRect(
        QRectF(
            r.left() + r.width() * 0.56,
            r.top() + r.height() * 0.2,
            bar_w,
            r.height() * 0.6,
        ),
        radius,
        radius,
    )


def _draw_prev(p: QPainter, r: QRectF, color: QColor) -> None:
    bar = QRectF(
        r.left() + r.width() * 0.12,
        r.top() + r.height() * 0.18,
        r.width() * 0.10,
        r.height() * 0.64,
    )
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawRect(bar)
    path = QPainterPath()
    path.moveTo(r.left() + r.width() * 0.78, r.top() + r.height() * 0.18)
    path.lineTo(r.left() + r.width() * 0.36, r.center().y())
    path.lineTo(r.left() + r.width() * 0.78, r.top() + r.height() * 0.82)
    path.closeSubpath()
    p.fillPath(
        path,
        color,
    )


def _draw_next(p: QPainter, r: QRectF, color: QColor) -> None:
    bar = QRectF(
        r.left() + r.width() * 0.78,
        r.top() + r.height() * 0.18,
        r.width() * 0.10,
        r.height() * 0.64,
    )
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawRect(bar)
    path = QPainterPath()
    path.moveTo(r.left() + r.width() * 0.22, r.top() + r.height() * 0.18)
    path.lineTo(r.left() + r.width() * 0.64, r.center().y())
    path.lineTo(r.left() + r.width() * 0.22, r.top() + r.height() * 0.82)
    path.closeSubpath()
    p.fillPath(path, color)


def _draw_heart(p: QPainter, r: QRectF, color: QColor, filled: bool) -> None:
    path = QPainterPath()
    path.moveTo(r.left() + r.width() * 0.5, r.top() + r.height() * 0.88)
    path.cubicTo(
        r.left() + r.width() * 0.06,
        r.top() + r.height() * 0.58,
        r.left() + r.width() * 0.08,
        r.top() + r.height() * 0.16,
        r.left() + r.width() * 0.34,
        r.top() + r.height() * 0.16,
    )
    path.cubicTo(
        r.left() + r.width() * 0.46,
        r.top() + r.height() * 0.16,
        r.left() + r.width() * 0.5,
        r.top() + r.height() * 0.26,
        r.left() + r.width() * 0.5,
        r.top() + r.height() * 0.26,
    )
    path.cubicTo(
        r.left() + r.width() * 0.5,
        r.top() + r.height() * 0.26,
        r.left() + r.width() * 0.54,
        r.top() + r.height() * 0.16,
        r.left() + r.width() * 0.66,
        r.top() + r.height() * 0.16,
    )
    path.cubicTo(
        r.left() + r.width() * 0.92,
        r.top() + r.height() * 0.16,
        r.left() + r.width() * 0.94,
        r.top() + r.height() * 0.58,
        r.left() + r.width() * 0.5,
        r.top() + r.height() * 0.88,
    )
    path.closeSubpath()
    if filled:
        p.fillPath(path, color)
    else:
        p.setPen(_pen(color, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


def _draw_shuffle(p: QPainter, r: QRectF, color: QColor) -> None:
    w = r.width()
    h = r.height()
    pen = _pen(color, max(1.5, r.width() * 0.05))
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    upper_y = r.top() + h * 0.34
    lower_y = r.top() + h * 0.66
    p.drawLine(
        QPointF(r.left() + w * 0.20, upper_y),
        QPointF(r.left() + w * 0.33, upper_y),
    )
    p.drawLine(
        QPointF(r.left() + w * 0.33, upper_y),
        QPointF(r.left() + w * 0.63, lower_y),
    )
    p.drawLine(
        QPointF(r.left() + w * 0.80, upper_y),
        QPointF(r.left() + w * 0.67, upper_y),
    )
    p.drawLine(
        QPointF(r.left() + w * 0.67, upper_y),
        QPointF(r.left() + w * 0.37, lower_y),
    )

    def arrow_head(tip: QPointF, dx: float, dy: float) -> QPolygonF:
        bx = tip.x() - dx * w * 0.13
        by = tip.y() - dy * h * 0.13
        px = -dy
        py = dx
        return QPolygonF(
            [
                tip,
                QPointF(bx + px * w * 0.075, by + py * h * 0.075),
                QPointF(bx - px * w * 0.075, by - py * h * 0.075),
            ]
        )

    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(arrow_head(QPointF(r.left() + w * 0.72, lower_y + h * 0.015), 1.0, 1.0))
    p.drawPolygon(arrow_head(QPointF(r.left() + w * 0.28, lower_y + h * 0.015), -1.0, 1.0))


def _draw_repeat(p: QPainter, r: QRectF, color: QColor, one: bool = False) -> None:
    w = r.width()
    h = r.height()
    pen = _pen(color, max(1.5, r.width() * 0.055))
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    left = r.left() + w * 0.26
    right = r.left() + w * 0.76
    top = r.top() + h * 0.28
    bottom = r.top() + h * 0.84
    radius = min(w, h) * 0.07
    path = QPainterPath()
    path.moveTo(right, r.top() + h * 0.52)
    path.lineTo(right, top + radius)
    path.cubicTo(right, top, right - radius, top, right - 2 * radius, top)
    path.lineTo(left + radius, top)
    path.cubicTo(left, top, left, top + radius, left, top + 2 * radius)
    path.lineTo(left, bottom - radius)
    path.cubicTo(left, bottom, left + radius, bottom, left + 2 * radius, bottom)
    path.lineTo(right - radius, bottom)
    path.cubicTo(right, bottom, right, bottom - radius, right, bottom - 2 * radius)
    path.lineTo(right, r.top() + h * 0.62)
    p.drawPath(path)

    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    head = QPolygonF(
        [
            QPointF(right, r.top() + h * 0.48),
            QPointF(right, r.top() + h * 0.64),
            QPointF(right + w * 0.12, r.top() + h * 0.56),
        ]
    )
    p.drawPolygon(head)
    if one:
        p.setPen(_pen(color, max(1.6, r.width() * 0.05)))
        p.drawLine(
            QPointF(r.left() + w * 0.53, r.top() + h * 0.38),
            QPointF(r.left() + w * 0.53, r.top() + h * 0.62),
        )


def _draw_order(p: QPainter, r: QRectF, color: QColor) -> None:
    w = r.width()
    h = r.height()
    pen = _pen(color, max(1.5, r.width() * 0.05))
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for y in (0.36, 0.70):
        y_abs = r.top() + h * y
        start = r.left() + w * 0.20
        end = r.left() + w * 0.62
        p.drawLine(QPointF(start, y_abs), QPointF(end, y_abs))
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        head = QPolygonF(
            [
                QPointF(end, y_abs - h * 0.10),
                QPointF(r.left() + w * 0.76, y_abs),
                QPointF(end, y_abs + h * 0.10),
            ]
        )
        p.drawPolygon(head)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)


def _draw_volume(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, max(1.4, r.width() * 0.04))
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    w = r.width()
    h = r.height()
    path = QPainterPath()
    top_left = QPointF(r.left() + w * 0.20, r.top() + h * 0.32)
    bottom_left = QPointF(r.left() + w * 0.20, r.top() + h * 0.56)
    left_mid = QPointF(r.left() + w * 0.175, r.top() + h * 0.44)
    top_right = QPointF(r.left() + w * 0.477, r.top() + h * 0.21)
    bottom_right = QPointF(r.left() + w * 0.477, r.top() + h * 0.70)
    path.moveTo(top_left)
    path.cubicTo(
        QPointF(r.left() + w * 0.19, r.top() + h * 0.33),
        QPointF(r.left() + w * 0.17, r.top() + h * 0.38),
        left_mid,
    )
    path.cubicTo(
        QPointF(r.left() + w * 0.17, r.top() + h * 0.50),
        QPointF(r.left() + w * 0.19, r.top() + h * 0.55),
        bottom_left,
    )
    path.lineTo(bottom_right)
    path.lineTo(top_right)
    path.closeSubpath()
    p.drawPath(path)

    p.drawArc(
        QRectF(
            r.left() + w * 0.56,
            r.top() + h * 0.39,
            w * 0.055,
            h * 0.15,
        ),
        270 * 16,
        180 * 16,
    )
    p.drawArc(
        QRectF(
            r.left() + w * 0.60,
            r.top() + h * 0.30,
            w * 0.095,
            h * 0.31,
        ),
        270 * 16,
        180 * 16,
    )


def _draw_search(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, 2.2)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(
        QRectF(r.left() + r.width() * 0.14, r.top() + r.height() * 0.14, r.width() * 0.5, r.height() * 0.5)
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.56, r.top() + r.height() * 0.56),
        QPointF(r.left() + r.width() * 0.86, r.top() + r.height() * 0.86),
    )


def _draw_folder(p: QPainter, r: QRectF, color: QColor) -> None:
    path = QPainterPath()
    path.moveTo(r.left() + r.width() * 0.14, r.top() + r.height() * 0.3)
    path.lineTo(r.left() + r.width() * 0.4, r.top() + r.height() * 0.3)
    path.lineTo(r.left() + r.width() * 0.5, r.top() + r.height() * 0.4)
    path.lineTo(r.left() + r.width() * 0.86, r.top() + r.height() * 0.4)
    path.lineTo(r.left() + r.width() * 0.86, r.top() + r.height() * 0.74)
    path.lineTo(r.left() + r.width() * 0.14, r.top() + r.height() * 0.74)
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(path)
    p.setBrush(QColor("#d7dce3"))
    p.drawRect(QRectF(r.left() + r.width() * 0.14, r.top() + r.height() * 0.64, r.width() * 0.72, r.height() * 0.1))


def _draw_refresh(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, 2.0)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(
        QRectF(r.left() + r.width() * 0.15, r.top() + r.height() * 0.15, r.width() * 0.7, r.height() * 0.7),
        60 * 16,
        270 * 16,
    )
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    head = QPolygonF(
        [
            QPointF(r.left() + r.width() * 0.2, r.top() + r.height() * 0.22),
            QPointF(r.left() + r.width() * 0.3, r.top() + r.height() * 0.14),
            QPointF(r.left() + r.width() * 0.36, r.top() + r.height() * 0.3),
        ]
    )
    p.drawPolygon(head)


def _draw_queue(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, 2.0)
    p.setPen(pen)
    y = r.top() + r.height() * 0.3
    for _ in range(3):
        p.drawLine(QPointF(r.left() + r.width() * 0.22, y), QPointF(r.left() + r.width() * 0.8, y))
        y += r.height() * 0.2
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    for x in (r.left() + r.width() * 0.12, r.left() + r.width() * 0.14):
        p.drawEllipse(QPointF(x, r.top() + r.height() * 0.3), r.width() * 0.04, r.width() * 0.04)


def _draw_close(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, 2.2)
    p.setPen(pen)
    p.drawLine(QPointF(r.left() + r.width() * 0.3, r.top() + r.height() * 0.3), QPointF(r.left() + r.width() * 0.7, r.top() + r.height() * 0.7))
    p.drawLine(QPointF(r.left() + r.width() * 0.7, r.top() + r.height() * 0.3), QPointF(r.left() + r.width() * 0.3, r.top() + r.height() * 0.7))


def _draw_arrow(p: QPainter, r: QRectF, color: QColor, left: bool) -> None:
    pen = _pen(color, 2.4)
    p.setPen(pen)
    cx = r.center().x()
    cy = r.center().y()
    if left:
        p.drawLine(QPointF(cx + r.width() * 0.2, r.top() + r.height() * 0.1), QPointF(cx - r.width() * 0.18, cy))
        p.drawLine(QPointF(cx - r.width() * 0.18, cy), QPointF(cx + r.width() * 0.2, r.top() + r.height() * 0.9))
    else:
        p.drawLine(QPointF(cx - r.width() * 0.2, r.top() + r.height() * 0.1), QPointF(cx + r.width() * 0.18, cy))
        p.drawLine(QPointF(cx + r.width() * 0.18, cy), QPointF(cx - r.width() * 0.2, r.top() + r.height() * 0.9))


def _draw_collapse(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, 2.4)
    p.setPen(pen)
    cx = r.center().x()
    top_y = r.top() + r.height() * 0.32
    bottom_y = r.top() + r.height() * 0.68
    p.drawLine(
        QPointF(cx - r.width() * 0.22, top_y),
        QPointF(cx, bottom_y),
    )
    p.drawLine(
        QPointF(cx, bottom_y),
        QPointF(cx + r.width() * 0.22, top_y),
    )


def _draw_plus(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, 2.2)
    p.setPen(pen)
    p.drawLine(QPointF(r.center().x(), r.top() + r.height() * 0.25), QPointF(r.center().x(), r.top() + r.height() * 0.75))
    p.drawLine(QPointF(r.left() + r.width() * 0.25, r.center().y()), QPointF(r.left() + r.width() * 0.75, r.center().y()))


def _draw_more(p: QPainter, r: QRectF, color: QColor) -> None:
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    for x in (0.3, 0.5, 0.7):
        p.drawEllipse(QPointF(r.left() + r.width() * x, r.center().y()), r.width() * 0.06, r.width() * 0.06)


def _draw_download(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, 2.2)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(r.center().x(), r.top() + r.height() * 0.2), QPointF(r.center().x(), r.top() + r.height() * 0.62))
    p.drawLine(QPointF(r.center().x(), r.top() + r.height() * 0.62), QPointF(r.left() + r.width() * 0.35, r.top() + r.height() * 0.48))
    p.drawLine(QPointF(r.center().x(), r.top() + r.height() * 0.62), QPointF(r.left() + r.width() * 0.65, r.top() + r.height() * 0.48))
    p.drawLine(QPointF(r.left() + r.width() * 0.24, r.top() + r.height() * 0.78), QPointF(r.left() + r.width() * 0.76, r.top() + r.height() * 0.78))


def _draw_minimize(p: QPainter, r: QRectF, color: QColor) -> None:
    p.setPen(_pen(color, 2.0))
    p.drawLine(
        QPointF(r.left() + r.width() * 0.28, r.center().y() + r.height() * 0.14),
        QPointF(r.left() + r.width() * 0.72, r.center().y() + r.height() * 0.14),
    )


def _draw_tray(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, 2.0)
    p.setPen(pen)
    cx = r.center().x()
    p.drawLine(
        QPointF(cx, r.top() + r.height() * 0.22),
        QPointF(cx, r.top() + r.height() * 0.62),
    )
    p.drawLine(
        QPointF(cx, r.top() + r.height() * 0.62),
        QPointF(r.left() + r.width() * 0.34, r.top() + r.height() * 0.48),
    )
    p.drawLine(
        QPointF(cx, r.top() + r.height() * 0.62),
        QPointF(r.left() + r.width() * 0.66, r.top() + r.height() * 0.48),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.24, r.top() + r.height() * 0.78),
        QPointF(r.left() + r.width() * 0.76, r.top() + r.height() * 0.78),
    )


def _draw_maximize(p: QPainter, r: QRectF, color: QColor) -> None:
    p.setPen(_pen(color, 1.9))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(
        QRectF(
            r.left() + r.width() * 0.28,
            r.top() + r.height() * 0.26,
            r.width() * 0.44,
            r.height() * 0.48,
        )
    )


def _draw_restore(p: QPainter, r: QRectF, color: QColor) -> None:
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(
        QRectF(
            r.left() + r.width() * 0.32,
            r.top() + r.height() * 0.3,
            r.width() * 0.38,
            r.height() * 0.4,
        )
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.42, r.top() + r.height() * 0.3),
        QPointF(r.left() + r.width() * 0.42, r.top() + r.height() * 0.2),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.42, r.top() + r.height() * 0.2),
        QPointF(r.left() + r.width() * 0.7, r.top() + r.height() * 0.2),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.7, r.top() + r.height() * 0.2),
        QPointF(r.left() + r.width() * 0.7, r.top() + r.height() * 0.46),
    )


def _draw_fullscreen(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, 2.0)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = 0.2
    s = 0.18
    x1 = r.left() + r.width() * m
    x2 = r.right() - r.width() * m
    y1 = r.top() + r.height() * m
    y2 = r.bottom() - r.height() * m
    p.drawLine(QPointF(x1, y1), QPointF(x1 + r.width() * s, y1))
    p.drawLine(QPointF(x1, y1), QPointF(x1, y1 + r.height() * s))
    p.drawLine(QPointF(x2, y1), QPointF(x2 - r.width() * s, y1))
    p.drawLine(QPointF(x2, y1), QPointF(x2, y1 + r.height() * s))
    p.drawLine(QPointF(x1, y2), QPointF(x1 + r.width() * s, y2))
    p.drawLine(QPointF(x1, y2), QPointF(x1, y2 - r.height() * s))
    p.drawLine(QPointF(x2, y2), QPointF(x2 - r.width() * s, y2))
    p.drawLine(QPointF(x2, y2), QPointF(x2, y2 - r.height() * s))


def _draw_lyric(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, 1.9)
    p.setPen(pen)
    for index, width in enumerate((0.5, 0.42, 0.34)):
        y = r.top() + r.height() * (0.28 + index * 0.24)
        p.drawLine(
            QPointF(r.left() + r.width() * 0.2, y),
            QPointF(r.left() + r.width() * (0.2 + width), y),
        )
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(
        QPointF(r.left() + r.width() * 0.76, r.top() + r.height() * 0.3),
        r.width() * 0.09,
        r.width() * 0.09,
    )


def _draw_desktop(p: QPainter, r: QRectF, color: QColor) -> None:
    p.setPen(_pen(color, 1.8))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(
        QRectF(
            r.left() + r.width() * 0.14,
            r.top() + r.height() * 0.22,
            r.width() * 0.72,
            r.height() * 0.5,
        ),
        2,
        2,
    )
    p.drawLine(
        QPointF(r.center().x(), r.top() + r.height() * 0.72),
        QPointF(r.center().x(), r.top() + r.height() * 0.84),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.3, r.top() + r.height() * 0.84),
        QPointF(r.left() + r.width() * 0.7, r.top() + r.height() * 0.84),
    )


def _draw_settings(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, 1.5)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for x, y in (
        (0.35, 0.32),
        (0.66, 0.22),
        (0.72, 0.5),
        (0.62, 0.78),
        (0.3, 0.7),
    ):
        p.drawEllipse(
            QPointF(r.left() + r.width() * x, r.top() + r.height() * y),
            r.width() * 0.07,
            r.height() * 0.07,
        )
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(
        QPointF(r.center().x(), r.center().y()),
        r.width() * 0.1,
        r.height() * 0.1,
    )


def _draw_logout(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, 1.8)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(
        QRectF(
            r.left() + r.width() * 0.18,
            r.top() + r.height() * 0.18,
            r.width() * 0.42,
            r.height() * 0.64,
        ),
        3,
        3,
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.52, r.center().y()),
        QPointF(r.left() + r.width() * 0.86, r.center().y()),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.7, r.top() + r.height() * 0.36),
        QPointF(r.left() + r.width() * 0.86, r.center().y()),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.7, r.top() + r.height() * 0.64),
        QPointF(r.left() + r.width() * 0.86, r.center().y()),
    )


def _draw_note(p: QPainter, r: QRectF, color: QColor) -> None:
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(
        QPointF(r.left() + r.width() * 0.34, r.top() + r.height() * 0.78),
        r.width() * 0.12,
        r.width() * 0.12,
    )
    p.drawEllipse(
        QPointF(r.left() + r.width() * 0.78, r.top() + r.height() * 0.64),
        r.width() * 0.12,
        r.width() * 0.12,
    )
    pen = _pen(color, max(1.6, r.width() * 0.06))
    p.setPen(pen)
    p.drawLine(
        QPointF(r.left() + r.width() * 0.44, r.top() + r.height() * 0.78),
        QPointF(r.left() + r.width() * 0.44, r.top() + r.height() * 0.22),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.88, r.top() + r.height() * 0.64),
        QPointF(r.left() + r.width() * 0.88, r.top() + r.height() * 0.14),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.88, r.top() + r.height() * 0.14),
        QPointF(r.left() + r.width() * 0.44, r.top() + r.height() * 0.22),
    )


def _draw_comment(p: QPainter, r: QRectF, color: QColor) -> None:
    p.setPen(_pen(color, 1.9))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(
        QRectF(
            r.left() + r.width() * 0.18,
            r.top() + r.height() * 0.2,
            r.width() * 0.64,
            r.height() * 0.48,
        ),
        4,
        4,
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.38, r.top() + r.height() * 0.68),
        QPointF(r.left() + r.width() * 0.32, r.top() + r.height() * 0.82),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.32, r.top() + r.height() * 0.82),
        QPointF(r.left() + r.width() * 0.52, r.top() + r.height() * 0.68),
    )


def _draw_message(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, 1.9)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(
        QRectF(
            r.left() + r.width() * 0.18,
            r.top() + r.height() * 0.22,
            r.width() * 0.64,
            r.height() * 0.46,
        ),
        4,
        4,
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.26, r.top() + r.height() * 0.68),
        QPointF(r.left() + r.width() * 0.34, r.top() + r.height() * 0.8),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.34, r.top() + r.height() * 0.8),
        QPointF(r.left() + r.width() * 0.46, r.top() + r.height() * 0.68),
    )
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(
        QPointF(r.left() + r.width() * 0.64, r.top() + r.height() * 0.42),
        r.width() * 0.06,
        r.width() * 0.06,
    )


def _draw_vip(p: QPainter, r: QRectF, color: QColor) -> None:
    path = QPainterPath()
    path.moveTo(r.left() + r.width() * 0.18, r.top() + r.height() * 0.32)
    path.lineTo(r.left() + r.width() * 0.38, r.top() + r.height() * 0.18)
    path.lineTo(r.center().x(), r.top() + r.height() * 0.36)
    path.lineTo(r.left() + r.width() * 0.62, r.top() + r.height() * 0.18)
    path.lineTo(r.left() + r.width() * 0.82, r.top() + r.height() * 0.32)
    path.lineTo(r.center().x(), r.top() + r.height() * 0.82)
    path.closeSubpath()
    p.setPen(_pen(color, 1.8))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.setPen(_pen(color, 2.0))
    p.drawLine(
        QPointF(r.center().x(), r.top() + r.height() * 0.34),
        QPointF(r.center().x(), r.top() + r.height() * 0.58),
    )
    p.drawLine(
        QPointF(r.center().x(), r.top() + r.height() * 0.7),
        QPointF(r.center().x(), r.top() + r.height() * 0.7),
    )


def _draw_qrcode(p: QPainter, r: QRectF, color: QColor) -> None:
    pen = _pen(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(
        QRectF(
            r.left() + r.width() * 0.16,
            r.top() + r.height() * 0.16,
            r.width() * 0.3,
            r.height() * 0.3,
        )
    )
    p.drawRect(
        QRectF(
            r.left() + r.width() * 0.54,
            r.top() + r.height() * 0.16,
            r.width() * 0.3,
            r.height() * 0.3,
        )
    )
    p.drawRect(
        QRectF(
            r.left() + r.width() * 0.16,
            r.top() + r.height() * 0.54,
            r.width() * 0.3,
            r.height() * 0.3,
        )
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.56, r.top() + r.height() * 0.56),
        QPointF(r.left() + r.width() * 0.56, r.top() + r.height() * 0.56),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.72, r.top() + r.height() * 0.56),
        QPointF(r.left() + r.width() * 0.72, r.top() + r.height() * 0.56),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.64, r.top() + r.height() * 0.72),
        QPointF(r.left() + r.width() * 0.64, r.top() + r.height() * 0.72),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.56, r.top() + r.height() * 0.72),
        QPointF(r.left() + r.width() * 0.84, r.top() + r.height() * 0.72),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.84, r.top() + r.height() * 0.56),
        QPointF(r.left() + r.width() * 0.84, r.top() + r.height() * 0.84),
    )
    p.drawLine(
        QPointF(r.left() + r.width() * 0.56, r.top() + r.height() * 0.84),
        QPointF(r.left() + r.width() * 0.84, r.top() + r.height() * 0.84),
    )


_DRAWERS = {
    "play": _draw_play,
    "pause": _draw_pause,
    "prev": _draw_prev,
    "next": _draw_next,
    "heart": lambda p, r, c: _draw_heart(p, r, c, False),
    "heart_fill": lambda p, r, c: _draw_heart(p, r, c, True),
    "order": _draw_order,
    "shuffle": _draw_shuffle,
    "repeat": lambda p, r, c: _draw_repeat(p, r, c, False),
    "repeat_one": lambda p, r, c: _draw_repeat(p, r, c, True),
    "volume": _draw_volume,
    "search": _draw_search,
    "folder": _draw_folder,
    "refresh": _draw_refresh,
    "queue": _draw_queue,
    "close": _draw_close,
    "back": lambda p, r, c: _draw_arrow(p, r, c, True),
    "forward": lambda p, r, c: _draw_arrow(p, r, c, False),
    "collapse": _draw_collapse,
    "plus": _draw_plus,
    "more": _draw_more,
    "download": _draw_download,
    "minimize": _draw_minimize,
    "tray": _draw_tray,
    "maximize": _draw_maximize,
    "restore": _draw_restore,
    "fullscreen": _draw_fullscreen,
    "lyric": _draw_lyric,
    "note": _draw_note,
    "desktop": _draw_desktop,
    "settings": _draw_settings,
    "logout": _draw_logout,
    "comment": _draw_comment,
    "message": _draw_message,
    "vip": _draw_vip,
    "qrcode": _draw_qrcode,
}


class IconButton(QPushButton):
    def __init__(
        self,
        icon_key: str = "play",
        size: int = 36,
        accent: bool = False,
        parent=None,
        image: str = "",
    ) -> None:
        super().__init__(parent)
        self._icon_key = icon_key
        self._accent = accent
        self._image_path = image
        self._icon_color = QColor("#c9ccd1")
        self._background: QColor | None = None
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTipDuration(800)
        self.setStyleSheet("background: transparent; border: none;")
        self._feedback = 0.0
        self._pulse = 0.0
        self._feedback_anim = QVariantAnimation(self)
        self._feedback_anim.setDuration(110)
        self._feedback_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._feedback_anim.valueChanged.connect(
            lambda value: self._set_feedback(float(value))
        )
        self._pulse_anim = QVariantAnimation(self)
        self._pulse_anim.setDuration(150)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._pulse_anim.valueChanged.connect(
            lambda value: self._set_pulse(float(value))
        )
        self._pulse_out = QVariantAnimation(self)
        self._pulse_out.setDuration(240)
        self._pulse_out.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._pulse_out.valueChanged.connect(
            lambda value: self._set_pulse(float(value))
        )

    def _set_feedback(self, value: float) -> None:
        self._feedback = max(0.0, min(1.0, value))
        self.update()

    def _set_pulse(self, value: float) -> None:
        self._pulse = max(0.0, min(1.0, value))
        self.update()

    def _animate_feedback(self, target: float) -> None:
        self._feedback_anim.stop()
        self._feedback_anim.setStartValue(self._feedback)
        self._feedback_anim.setEndValue(target)
        self._feedback_anim.start()

    def _bump_pulse(self) -> None:
        self._pulse_out.stop()
        self._pulse_anim.stop()
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.finished.connect(self._pulse_fall, Qt.ConnectionType.UniqueConnection)
        self._pulse_anim.start()

    def _pulse_fall(self) -> None:
        self._pulse_out.setStartValue(self._pulse)
        self._pulse_out.setEndValue(0.0)
        self._pulse_out.start()

    def enterEvent(self, event) -> None:
        if self.isEnabled():
            self._animate_feedback(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_feedback(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._bump_pulse()
        super().mousePressEvent(event)

    def set_icon(self, icon_key: str) -> None:
        if icon_key != self._icon_key:
            self._icon_key = icon_key
            self._bump_pulse()
        self.update()

    def set_icon_color(self, color: QColor) -> None:
        self._icon_color = color
        self.update()

    def set_solid_background(self, color: QColor) -> None:
        self._background = QColor(color)
        self.update()

    def set_accent(self, accent: bool) -> None:
        self._accent = accent
        self.update()

    def set_image(self, path: str) -> None:
        self._image_path = path
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        hovered = self.underMouse() and self.isEnabled()
        down = self.isDown()
        feedback = self._feedback if hovered else 0.0
        pulse = self._pulse
        scale = 1.0 + pulse * 0.045 + feedback * 0.015
        shrink = 0.94 if down else 1.0
        glyph_rect = QRectF(
            rect.center().x() - rect.width() * scale * shrink / 2.0,
            rect.center().y() - rect.height() * scale * shrink / 2.0,
            rect.width() * scale * shrink,
            rect.height() * scale * shrink,
        )

        pixmap = _load_pixmap(self._image_path)
        if pixmap is not None:
            clip = QPainterPath()
            clip.addEllipse(glyph_rect)
            painter.save()
            painter.setClipPath(clip)
            painter.drawPixmap(glyph_rect.toAlignedRect(), pixmap)
            painter.restore()
            return

        if self._accent:
            color = _lerp_color(
                QColor("#ec4141"), QColor("#ff5b52"), feedback
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(glyph_rect)
            glyph = WHITE
        else:
            if self._background is not None:
                bg = QColor(self._background)
                base = bg.darker(112) if down else bg
                hover = bg.lighter(114)
                bg = _lerp_color(base, hover, feedback)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(bg)
                painter.drawEllipse(glyph_rect)
                glyph = self._icon_color
            else:
                glyph = _lerp_color(
                    self._icon_color, QColor("#ffffff"), feedback * 0.85
                )
                if feedback > 0.01:
                    halo = QRadialGradient(
                        glyph_rect.center(), glyph_rect.width() / 2.0
                    )
                    halo.setColorAt(
                        0.0,
                        QColor(255, 90, 90, int(26 * feedback + pulse * 20)),
                    )
                    halo.setColorAt(
                        0.72,
                        QColor(255, 90, 90, int(10 * feedback)),
                    )
                    halo.setColorAt(1.0, QColor(255, 90, 90, 0))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(halo)
                    painter.drawEllipse(glyph_rect)

        inner = QRectF(
            glyph_rect.left() + glyph_rect.width() * 0.12,
            glyph_rect.top() + glyph_rect.height() * 0.12,
            glyph_rect.width() * 0.76,
            glyph_rect.height() * 0.76,
        )
        if self._accent:
            inner = QRectF(
                glyph_rect.left() + glyph_rect.width() * 0.2,
                glyph_rect.top() + glyph_rect.height() * 0.2,
                glyph_rect.width() * 0.6,
                glyph_rect.height() * 0.6,
            )
        if self._icon_key in ("heart_fill", "heart"):
            inner = QRectF(
                glyph_rect.left() + glyph_rect.width() * 0.14,
                glyph_rect.top() + glyph_rect.height() * 0.14,
                glyph_rect.width() * 0.72,
                glyph_rect.height() * 0.72,
            )
        if self._icon_key == "volume":
            inner = QRectF(
                glyph_rect.left() + glyph_rect.width() * 0.04,
                glyph_rect.top() + glyph_rect.height() * 0.04,
                glyph_rect.width() * 0.92,
                glyph_rect.height() * 0.92,
            )
        drawer = _DRAWERS.get(self._icon_key)
        if drawer is not None:
            drawer(painter, inner, glyph)
        else:
            painter.setPen(_pen(glyph, 2.0))
            painter.drawText(
                glyph_rect, Qt.AlignmentFlag.AlignCenter, self.text()
            )
