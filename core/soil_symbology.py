# -*- coding: utf-8 -*-
"""
Simbología edafológica y estratigráfica compartida (vista previa del cursor y PDF).

Patrones inspirados en las convenciones litológicas habituales (USGS/FGDC):
punteado para arenas, rayado horizontal para arcillas, círculos para gravas,
ladrillos para calizas, etc. Todo se dibuja con QPainter, así que sirve tanto
para pantalla como para imágenes de alta resolución del informe.
"""

import random

from qgis.PyQt.QtCore import Qt, QPointF, QRectF
from qgis.PyQt.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)

from .profile_engine import ProfileGeometry

# (clave, palabras clave, nombre para la leyenda)
_PATTERNS = [
    ("organic", ("orgánica", "organica", "organic", "humus"), "Materia orgánica"),
    ("peat", ("turba", "peat"), "Turba"),
    ("coal", ("carbón", "carbon", "coal"), "Carbón"),
    ("ash", ("ceniza", "ash", "tefra", "tephra"), "Ceniza volcánica"),
    ("gypsum", ("yeso", "gypsum"), "Yeso"),
    ("salt", ("sal", "salt", "evaporit"), "Sal / evaporitas"),
    ("limestone", ("caliza", "limestone", "calcáre", "carbonat"), "Caliza"),
    ("schist", ("esquisto", "schist", "pizarra", "slate", "lutita"), "Esquisto"),
    ("rock", ("roca", "rock", "granit", "basalt", "bedrock"), "Roca"),
    ("gravel", ("grava", "gravel", "clasto", "pedregos"), "Grava"),
    ("sandy_clay", ("arcilla arenosa", "sandy clay"), "Arcilla arenosa"),
    ("silty_clay", ("limo arcilloso", "silty clay"), "Limo arcilloso"),
    (
        "clay_loam",
        ("franco-arcilloso", "franco arcilloso", "clay loam"),
        "Franco arcilloso",
    ),
    (
        "sandy_loam",
        ("franco-arenoso", "franco arenoso", "sandy loam"),
        "Franco arenoso",
    ),
    ("clay", ("arcilla", "clay"), "Arcilla"),
    ("silt", ("limo", "silt"), "Limo"),
    ("sand", ("arena", "sand"), "Arena"),
    ("loam", ("franco", "loam"), "Franco"),
]

BOUNDARY_TYPES = [
    ("abrupt", "Abrupto (< 2,5 cm)"),
    ("clear", "Claro (2,5 – 7,5 cm)"),
    ("gradual", "Gradual (7,5 – 12,5 cm)"),
    ("diffuse", "Difuso (> 12,5 cm)"),
]


def pattern_key(texture):
    """Devuelve (clave, nombre de leyenda) del patrón para un material/textura."""
    t = (texture or "").lower()
    for key, words, label in _PATTERNS:
        if any(w in t for w in words):
            return key, label
    return "generic", texture or "Sin clasificar"


def boundary_pen(boundary_type, width=1.0, color=QColor(30, 30, 30)):
    """Lápiz para un límite según su nitidez (abrupto → difuso)."""
    pen = QPen(color)
    pen.setCosmetic(False)
    if boundary_type == "abrupt":
        pen.setWidthF(1.8 * width)
        pen.setStyle(Qt.PenStyle.SolidLine)
    elif boundary_type == "gradual":
        pen.setWidthF(1.0 * width)
        pen.setStyle(Qt.PenStyle.DashLine)
    elif boundary_type == "diffuse":
        pen.setWidthF(1.0 * width)
        pen.setStyle(Qt.PenStyle.DotLine)
    else:  # clear
        pen.setWidthF(1.1 * width)
        pen.setStyle(Qt.PenStyle.SolidLine)
    return pen


def _ink(alpha=150):
    return QColor(20, 20, 20, alpha)


def draw_pattern(painter, area, texture, unit=1.0, alpha=150):
    """Rellena 'area' (QRectF o QPainterPath) con el patrón del material.

    unit: tamaño base del patrón en px (1.0 = pantalla; ~4 para imágenes a 300 ppp).
    """
    key, _ = pattern_key(texture)
    path = area if isinstance(area, QPainterPath) else _rect_path(area)
    r = path.boundingRect()
    if r.width() <= 0 or r.height() <= 0:
        return

    painter.save()
    painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(_ink(alpha))
    pen.setWidthF(max(0.6, 0.7 * unit))
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    rng = random.Random(sum(ord(c) for c in key))  # estable entre ejecuciones
    u = unit
    x0, y0, x1, y1 = r.left(), r.top(), r.right(), r.bottom()

    def frange(a, b, s):
        v = a
        while v < b:
            yield v
            v += s

    if key == "sand":
        painter.setBrush(QBrush(_ink(alpha)))
        painter.setPen(Qt.PenStyle.NoPen)
        for y in frange(y0, y1, 5 * u):
            for x in frange(x0, x1, 5 * u):
                jx, jy = rng.uniform(-1.6, 1.6) * u, rng.uniform(-1.6, 1.6) * u
                painter.drawEllipse(QPointF(x + jx, y + jy), 0.55 * u, 0.55 * u)
    elif key == "clay":
        for y in frange(y0, y1, 4 * u):
            painter.drawLine(QPointF(x0, y), QPointF(x1, y))
    elif key == "silt":
        row = 0
        for y in frange(y0, y1, 4.5 * u):
            shift = (row % 2) * 4 * u
            for x in frange(x0 - 8 * u + shift, x1, 8 * u):
                painter.drawLine(QPointF(x, y), QPointF(x + 4.5 * u, y))
            row += 1
    elif key == "loam":
        row = 0
        for y in frange(y0, y1, 5 * u):
            shift = (row % 2) * 5 * u
            for x in frange(x0 - 10 * u + shift, x1, 10 * u):
                painter.drawLine(QPointF(x, y), QPointF(x + 4 * u, y))
                painter.drawPoint(QPointF(x + 7 * u, y))
            row += 1
    elif key in ("clay_loam", "silty_clay"):
        row = 0
        for y in frange(y0, y1, 4 * u):
            if row % 2 == 0:
                painter.drawLine(QPointF(x0, y), QPointF(x1, y))
            else:
                for x in frange(x0, x1, 6 * u):
                    if key == "clay_loam":
                        painter.drawPoint(QPointF(x, y))
                    else:
                        painter.drawLine(QPointF(x, y), QPointF(x + 3 * u, y))
            row += 1
    elif key in ("sandy_loam", "sandy_clay"):
        painter.setBrush(QBrush(_ink(alpha)))
        row = 0
        for y in frange(y0, y1, 4.5 * u):
            for x in frange(x0, x1, 5 * u):
                if row % 2 == 0 and key == "sandy_clay":
                    continue
                painter.setPen(Qt.PenStyle.NoPen)
                jx = rng.uniform(-1.2, 1.2) * u
                painter.drawEllipse(QPointF(x + jx, y), 0.5 * u, 0.5 * u)
            if row % 2 == 0:
                painter.setPen(pen)
                if key == "sandy_clay":
                    painter.drawLine(QPointF(x0, y), QPointF(x1, y))
                else:
                    for x in frange(x0, x1, 10 * u):
                        painter.drawLine(QPointF(x, y), QPointF(x + 4 * u, y))
            row += 1
    elif key == "gravel":
        for y in frange(y0, y1, 7 * u):
            for x in frange(x0, x1, 7 * u):
                rx = rng.uniform(1.2, 2.4) * u
                ry = rx * rng.uniform(0.6, 1.0)
                jx, jy = rng.uniform(-1.5, 1.5) * u, rng.uniform(-1.5, 1.5) * u
                painter.drawEllipse(QPointF(x + 3.5 * u + jx, y + 3.5 * u + jy), rx, ry)
    elif key == "rock":
        # Bloques irregulares con fracturas (roca masiva / basamento)
        row = 0
        for y in frange(y0, y1, 8 * u):
            painter.drawLine(QPointF(x0, y), QPointF(x1, y))
            shift = (row % 2) * 6 * u
            for x in frange(x0 + shift, x1, 12 * u):
                painter.drawLine(QPointF(x, y), QPointF(x + 2 * u, y + 8 * u))
            row += 1
    elif key == "limestone":
        row = 0
        for y in frange(y0, y1, 6 * u):
            painter.drawLine(QPointF(x0, y), QPointF(x1, y))
            shift = (row % 2) * 7 * u
            for x in frange(x0 + shift, x1, 14 * u):
                painter.drawLine(QPointF(x, y), QPointF(x, y + 6 * u))
            row += 1
    elif key == "schist":
        for y in frange(y0, y1, 3.5 * u):
            p = QPainterPath(QPointF(x0, y))
            x = x0
            up = True
            while x < x1:
                p.quadTo(
                    QPointF(x + 3 * u, y + (-1.2 if up else 1.2) * u),
                    QPointF(x + 6 * u, y),
                )
                x += 6 * u
                up = not up
            painter.drawPath(p)
    elif key in ("organic", "peat"):
        # Símbolo de turba/materia orgánica: trazos horizontales con 'pasto'
        row = 0
        for y in frange(y0 + 4 * u, y1, 6 * u):
            shift = (row % 2) * 6 * u
            for x in frange(x0 + shift, x1, 12 * u):
                painter.drawLine(QPointF(x, y), QPointF(x + 6 * u, y))
                if key == "peat" or row % 2 == 0:
                    painter.drawLine(
                        QPointF(x + 3 * u, y), QPointF(x + 1.5 * u, y - 2.5 * u)
                    )
                    painter.drawLine(
                        QPointF(x + 3 * u, y), QPointF(x + 4.5 * u, y - 2.5 * u)
                    )
            row += 1
    elif key == "coal":
        painter.fillPath(path, QBrush(QColor(15, 15, 15, 170)))
        pen.setColor(QColor(255, 255, 255, 90))
        painter.setPen(pen)
        for y in frange(y0, y1, 5 * u):
            painter.drawLine(QPointF(x0, y), QPointF(x1, y))
    elif key == "ash":
        for y in frange(y0, y1, 6 * u):
            for x in frange(x0, x1, 6 * u):
                jx = rng.uniform(-1, 1) * u
                painter.drawLine(
                    QPointF(x + jx, y), QPointF(x + jx + 1.5 * u, y + 2.5 * u)
                )
                painter.drawLine(
                    QPointF(x + jx + 1.5 * u, y + 2.5 * u), QPointF(x + jx + 3 * u, y)
                )
    elif key == "gypsum":
        row = 0
        for y in frange(y0, y1, 6 * u):
            shift = (row % 2) * 4 * u
            for x in frange(x0 + shift, x1, 8 * u):
                painter.drawLine(QPointF(x, y), QPointF(x + 3 * u, y + 3 * u))
                painter.drawLine(QPointF(x + 3 * u, y), QPointF(x, y + 3 * u))
            row += 1
    elif key == "salt":
        row = 0
        for y in frange(y0, y1, 6 * u):
            shift = (row % 2) * 3 * u
            for x in frange(x0 + shift, x1, 6 * u):
                painter.drawRect(QRectF(x, y, 2.6 * u, 2.6 * u))
            row += 1
    else:
        for y in frange(y0, y1, 6 * u):
            for x in frange(x0, x1, 6 * u):
                painter.drawPoint(QPointF(x, y))

    painter.restore()


def _rect_path(rect):
    p = QPainterPath()
    p.addRect(QRectF(rect))
    return p


def nice_step(total_cm, target_ticks=8):
    """Paso 'redondo' para la regla de profundidad."""
    raw = max(total_cm / max(target_ticks, 1), 1)
    for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if s >= raw:
            return s
    return 1000


def draw_profile_column(
    painter,
    rect,
    horizons,
    unit=1.0,
    shaped=True,
    labels=True,
    ruler=True,
    ruler_width=None,
    font_px=None,
    font_family=None,
):
    """Dibuja una columna de perfil profesional dentro de rect.

    - Relleno con el color Munsell/RGB del horizonte + patrón del material.
    - Límites con estilo según su nitidez (abrupto, claro, gradual, difuso).
    - Regla de profundidad (cm) a la izquierda y nombre de cada horizonte.
    shaped=False dibuja límites rectos (columna esquemática).
    """
    if not horizons:
        return
    rect = QRectF(rect)
    total = max(h.bottom for h in horizons) or 1.0
    ruler_w = (ruler_width if ruler_width is not None else 14 * unit) if ruler else 0
    col = QRectF(
        rect.left() + ruler_w, rect.top(), rect.width() - ruler_w, rect.height()
    )
    scale = col.height() / total
    fpx = font_px or max(7.0, 3.2 * unit)

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if shaped:
        style = col.width() / 300.0
        bounds = ProfileGeometry.compute_boundaries(horizons, col.width(), scale, style)
        bounds = [
            [QPointF(p.x() + col.left(), p.y() + col.top()) for p in b] for b in bounds
        ]
        if not horizons[0].top_offsets:
            # Sin forma manual, la superficie del perfil es la línea de 0 cm
            bounds[0] = [QPointF(p.x(), col.top()) for p in bounds[0]]
        bounds = [
            [QPointF(p.x(), min(max(p.y(), col.top()), col.bottom())) for p in b]
            for b in bounds
        ]
    else:
        bounds = [[QPointF(col.left(), col.top()), QPointF(col.right(), col.top())]]
        for h in horizons:
            y = col.top() + h.bottom * scale
            bounds.append([QPointF(col.left(), y), QPointF(col.right(), y)])

    frame = QPainterPath()
    frame.addRect(col)
    painter.setClipPath(frame)

    for i, h in enumerate(horizons):
        top_b, bot_b = bounds[i], bounds[i + 1]
        path = QPainterPath(top_b[0])
        for p in top_b[1:]:
            path.lineTo(p)
        for p in reversed(bot_b):
            path.lineTo(p)
        path.closeSubpath()
        painter.fillPath(path, QBrush(h.color))
        draw_pattern(painter, path, h.texture, unit=unit)

    # Límites (la base del último se dibuja como línea simple)
    for i, h in enumerate(horizons):
        b = bounds[i + 1]
        line = QPainterPath(b[0])
        for p in b[1:]:
            line.lineTo(p)
        painter.setPen(boundary_pen(h.boundary_type, width=unit * 0.6))
        painter.drawPath(line)

    painter.setClipping(False)
    painter.setPen(QPen(QColor(25, 25, 25), 1.2 * unit * 0.6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(col)

    font = QFont(font_family) if font_family else QFont()
    font.setPixelSize(int(round(fpx)))

    if labels:
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        min_h = fpx * 1.5
        for h in horizons:
            y_top = col.top() + h.top * scale
            y_bot = col.top() + h.bottom * scale
            if y_bot - y_top < min_h:
                continue
            # Etiqueta tipo 'chip' blanco, centrada verticalmente en el horizonte
            tw = fm.horizontalAdvance(h.name) + fpx * 0.8
            th = fpx * 1.35
            chip = QRectF(col.left() + fpx * 0.5, (y_top + y_bot - th) / 2, tw, th)
            painter.setPen(QPen(QColor(60, 60, 60, 160), max(1.0, unit * 0.25)))
            painter.setBrush(QColor(255, 255, 255, 225))
            painter.drawRoundedRect(chip, th * 0.25, th * 0.25)
            painter.setPen(QColor(20, 20, 20))
            painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, h.name)

    if ruler:
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QPen(QColor(40, 40, 40), 0.8 * unit * 0.6))
        x = col.left()
        painter.drawLine(
            QPointF(x - 1.5 * unit, col.top()), QPointF(x - 1.5 * unit, col.bottom())
        )
        step = nice_step(total, max(3, int(col.height() / (fpx * 3.2))))
        d = 0
        while d <= total + 1e-6:
            y = col.top() + d * scale
            painter.drawLine(
                QPointF(x - 1.5 * unit - 3 * unit, y), QPointF(x - 1.5 * unit, y)
            )
            painter.drawText(
                QRectF(rect.left(), y - fpx, ruler_w - 5 * unit - fpx * 0.35, 2 * fpx),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{d:g}",
            )
            d += step
        minor = step / 5 if step >= 5 else None
        if minor:
            d = 0
            while d <= total + 1e-6:
                y = col.top() + d * scale
                painter.drawLine(
                    QPointF(x - 1.5 * unit - 1.5 * unit, y), QPointF(x - 1.5 * unit, y)
                )
                d += minor
    painter.restore()


def render_column_image(
    horizons,
    width_px,
    height_px,
    unit,
    shaped=True,
    labels=True,
    ruler=True,
    ruler_width=None,
    font_px=None,
    font_family="Arial",
):
    """QImage (fondo blanco) con la columna del perfil, para el PDF."""
    img = QImage(int(width_px), int(height_px), QImage.Format.Format_ARGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    pad_x = 2 * unit
    pad_y = (font_px or 4 * unit) * 0.8
    draw_profile_column(
        p,
        QRectF(pad_x, pad_y, width_px - 2 * pad_x, height_px - 2 * pad_y),
        horizons,
        unit=unit,
        shaped=shaped,
        labels=labels,
        ruler=ruler,
        ruler_width=ruler_width,
        font_px=font_px,
        font_family=font_family,
    )
    p.end()
    return img


def render_swatch_image(texture, color, width_px, height_px, unit):
    """Muestra de leyenda: color + patrón del material, con borde."""
    img = QImage(int(width_px), int(height_px), QImage.Format.Format_ARGB32)
    img.fill(QColor(255, 255, 255, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(unit * 0.5, unit * 0.5, width_px - unit, height_px - unit)
    p.fillRect(r, QBrush(QColor(color)))
    draw_pattern(p, r, texture, unit=unit)
    p.setPen(QPen(QColor(30, 30, 30), max(1.0, unit * 0.4)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(r)
    p.end()
    return img


def render_boundary_swatch(boundary_type, width_px, height_px, unit):
    """Muestra de leyenda para un tipo de límite."""
    img = QImage(int(width_px), int(height_px), QImage.Format.Format_ARGB32)
    img.fill(QColor(255, 255, 255, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(boundary_pen(boundary_type, width=unit * 0.9))
    y = height_px / 2
    p.drawLine(QPointF(unit, y), QPointF(width_px - unit, y))
    p.end()
    return img
