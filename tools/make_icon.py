"""Generate resources/icon.ico — academic torch-and-book university emblem."""
from __future__ import annotations

import io
import math
import sys
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QBrush, QColor, QImage, QLinearGradient,
    QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import QApplication


NAVY_TOP  = "#0D1B4B"   # prestige navy (top)
NAVY_BOT  = "#1A237E"   # deep indigo blue (bottom)
GOLD      = "#C9A227"   # traditional academic gold
GOLD_LITE = "#E8C84A"   # lighter gold highlight
GOLD_DIM  = "#7B5E0C"   # dark gold / bronze shadow
PARCHMENT = "#F5F0E8"   # ivory / parchment page
PAGE_LINE = "#B0A090"   # warm gray text lines

SIZES = (256, 128, 64, 48, 32, 16)


def _draw_background(p: QPainter, size: int) -> None:
    grad = QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0.0, QColor(NAVY_TOP))
    grad.setColorAt(1.0, QColor(NAVY_BOT))
    path = QPainterPath()
    corner = size * 0.15
    path.addRoundedRect(0, 0, size, size, corner, corner)
    p.fillPath(path, QBrush(grad))


def _draw_frame(p: QPainter, size: int) -> None:
    """Thin gold inner border — diploma / seal aesthetic."""
    if size < 48:
        return
    inset = size * 0.055
    br = size * 0.10
    frame = QPainterPath()
    frame.addRoundedRect(inset, inset, size - 2 * inset, size - 2 * inset, br, br)
    p.setPen(QPen(QColor(GOLD), max(1.0, size * 0.016)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(frame)


def _star_path(cx: float, cy: float, r_out: float, r_in: float, n: int = 5) -> QPainterPath:
    path = QPainterPath()
    for i in range(n * 2):
        r = r_out if i % 2 == 0 else r_in
        angle = math.pi * i / n - math.pi / 2
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    return path


def _draw_stars(p: QPainter, size: int) -> None:
    """Two small gold stars flanking the torch handle."""
    if size < 64:
        return
    r_out  = size * 0.033
    r_in   = r_out * 0.42
    star_y = size * 0.290

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(GOLD_LITE)))
    for star_x in (size * 0.290, size * 0.710):
        p.drawPath(_star_path(star_x, star_y, r_out, r_in))


def _draw_torch(p: QPainter, size: int) -> None:
    """Classic academic torch: bezier flame + cylindrical handle with gradient."""
    cx = size * 0.50

    # ── flame ────────────────────────────────────────────────────────────────
    fl_top  = size * 0.072
    fl_base = size * 0.248
    fl_w    = size * 0.100

    flame = QPainterPath()
    flame.moveTo(cx, fl_base)
    flame.cubicTo(cx - fl_w * 0.95, fl_base - (fl_base - fl_top) * 0.33,
                  cx - fl_w * 0.60, fl_top + (fl_base - fl_top) * 0.10,
                  cx,               fl_top)
    flame.cubicTo(cx + fl_w * 0.60, fl_top + (fl_base - fl_top) * 0.10,
                  cx + fl_w * 0.95, fl_base - (fl_base - fl_top) * 0.33,
                  cx,               fl_base)
    flame.closeSubpath()

    flame_grad = QLinearGradient(cx, fl_top, cx, fl_base)
    flame_grad.setColorAt(0.00, QColor("#FFFFFF"))
    flame_grad.setColorAt(0.22, QColor(GOLD_LITE))
    flame_grad.setColorAt(1.00, QColor(GOLD))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(flame_grad))
    p.drawPath(flame)

    # inner amber core (only large enough sizes)
    if size >= 48:
        cw = fl_w * 0.42
        ct = fl_top + (fl_base - fl_top) * 0.22
        core = QPainterPath()
        core.moveTo(cx, fl_base)
        core.cubicTo(cx - cw,       fl_base - (fl_base - ct) * 0.40,
                     cx - cw * 0.5, ct + (fl_base - ct) * 0.10,
                     cx,            ct)
        core.cubicTo(cx + cw * 0.5, ct + (fl_base - ct) * 0.10,
                     cx + cw,       fl_base - (fl_base - ct) * 0.40,
                     cx,            fl_base)
        core.closeSubpath()
        p.setBrush(QBrush(QColor("#FF8C00")))
        p.drawPath(core)

    # ── handle ───────────────────────────────────────────────────────────────
    hnd_top = fl_base - size * 0.010
    hnd_bot = size * 0.385
    hnd_w   = size * 0.052

    hnd_grad = QLinearGradient(cx - hnd_w, 0, cx + hnd_w, 0)
    hnd_grad.setColorAt(0.0, QColor(GOLD_DIM))
    hnd_grad.setColorAt(0.4, QColor(GOLD))
    hnd_grad.setColorAt(0.7, QColor(GOLD_LITE))
    hnd_grad.setColorAt(1.0, QColor(GOLD_DIM))
    p.setBrush(QBrush(hnd_grad))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(int(cx - hnd_w), int(hnd_top),
               int(hnd_w * 2),  int(hnd_bot - hnd_top))

    # base knob — wider cap at the bottom of the handle
    knob_w = hnd_w * 1.55
    knob_h = size * 0.024
    p.drawRect(int(cx - knob_w), int(hnd_bot - knob_h),
               int(knob_w * 2),  int(knob_h))


def _draw_book(p: QPainter, size: int) -> None:
    bk_cx  = size * 0.50
    bk_cy  = size * 0.645
    bk_w   = size * 0.74
    bk_h   = size * 0.370
    bk_top = bk_cy - bk_h * 0.5
    bk_bot = bk_cy + bk_h * 0.5
    spine  = bk_cx
    page_w = bk_w * 0.47
    splay  = size * 0.036

    def make_page(left: bool) -> QPainterPath:
        path = QPainterPath()
        if left:
            path.moveTo(spine - page_w - splay, bk_top - splay * 0.35)
            path.lineTo(spine - size * 0.012,   bk_top)
            path.lineTo(spine - size * 0.012,   bk_bot)
            path.lineTo(spine - page_w - splay, bk_bot + splay * 0.35)
        else:
            path.moveTo(spine + size * 0.012,   bk_top)
            path.lineTo(spine + page_w + splay, bk_top - splay * 0.35)
            path.lineTo(spine + page_w + splay, bk_bot + splay * 0.35)
            path.lineTo(spine + size * 0.012,   bk_bot)
        path.closeSubpath()
        return path

    for left in (True, False):
        pg = make_page(left)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(PARCHMENT)))
        p.drawPath(pg)
        p.setPen(QPen(QColor(GOLD_DIM), max(1.0, size * 0.010)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(pg)

    # gold spine
    p.setPen(QPen(QColor(GOLD), max(1.5, size * 0.016)))
    p.drawLine(int(spine), int(bk_top), int(spine), int(bk_bot))

    # parchment text lines
    if size >= 48:
        line_pen = QPen(QColor(PAGE_LINE), max(1.0, size * 0.013))
        line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(line_pen)
        for frac in (0.20, 0.38, 0.56, 0.72):
            ly = int(bk_top + bk_h * frac)
            p.drawLine(int(spine - page_w * 0.82), ly, int(spine - size * 0.045), ly)
            p.drawLine(int(spine + size * 0.045), ly, int(spine + page_w * 0.82), ly)


def draw_icon(size: int) -> Image.Image:
    from PyQt6.QtCore import QBuffer, QIODevice
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    _draw_background(p, size)
    _draw_frame(p, size)
    _draw_book(p, size)
    _draw_torch(p, size)
    _draw_stars(p, size)

    p.end()

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


def main() -> int:
    app = QApplication(sys.argv)
    root = Path(__file__).resolve().parent.parent
    out = root / "resources" / "icon.ico"
    out.parent.mkdir(parents=True, exist_ok=True)

    frames = [draw_icon(s) for s in SIZES]
    base = frames[0]
    base.save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    base.save(root / "resources" / "icon.png", format="PNG")
    print(f"Wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
