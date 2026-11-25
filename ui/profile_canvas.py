# -*- coding: utf-8 -*-
import os
from qgis.PyQt.QtWidgets import QWidget
from qgis.PyQt.QtGui import (
    QPainter,
    QPen,
    QBrush,
    QColor,
    QPainterPath,
    QLinearGradient,
    QPixmap,
)
from qgis.PyQt.QtCore import Qt, QRectF, QPointF, pyqtSignal
from ..core.profile_engine import ProfileGeometry, SHAPE_POINTS, normalize_offsets

# Límite de desplazamiento manual de un punto (cm)
MAX_SHAPE_OFFSET_CM = 300.0
HANDLE_RADIUS = 5
HANDLE_HIT_RADIUS = 9


class EdafoCanvas(QWidget):
    # Se emite al terminar una edición manual de forma (lápiz)
    shapeEdited = pyqtSignal()
    # Se emite al activar/desactivar el modo lápiz
    editModeChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.horizons = []
        self.setMinimumSize(300, 600)
        self.scale_factor = 3  # 1 cm = 3 pixels (base, usado en exportación)
        self._current_scale = 3.0  # escala actual (modificable con zoom)
        self.show_fault_line = False  # Control de visibilidad del plano de falla
        # Caché de geometría: se calcula una vez y se reutiliza en cada paintEvent
        self._cached_paths = []  # lista de (QPainterPath, HorizonData)
        self._boundaries = (
            []
        )  # límites calculados (superficie + base de cada horizonte)
        self._cache_width = -1  # ancho con el que se calculó el caché
        # Bandera para evitar recursión de paint events
        self._in_paint_event = False
        # Offset vertical de scroll (para panorámica con arrastre)
        self._scroll_offset = 0
        # --- Edición manual de forma (lápiz) ---
        self.edit_mode = False
        self._hover = None  # (índice de límite, índice de punto)
        self._drag = None  # dict con el estado del arrastre
        self._undo_stack = []

    # ------------------------------------------------------------------
    # Edición manual de forma (lápiz)
    # ------------------------------------------------------------------
    def set_edit_mode(self, enabled):
        """Activa o desactiva el modo lápiz (arrastrar límites)."""
        self.edit_mode = bool(enabled)
        self.setMouseTracking(self.edit_mode)
        self._hover = None
        self._drag = None
        self.setCursor(
            Qt.CursorShape.CrossCursor if self.edit_mode else Qt.CursorShape.ArrowCursor
        )
        self.editModeChanged.emit(self.edit_mode)
        self.update()

    def can_undo(self):
        return bool(self._undo_stack)

    def has_shapes(self):
        return any(
            h.bottom_offsets or (i == 0 and h.top_offsets)
            for i, h in enumerate(self.horizons)
        )

    def _snapshot(self):
        return [
            (
                list(h.top_offsets) if h.top_offsets else None,
                list(h.bottom_offsets) if h.bottom_offsets else None,
            )
            for h in self.horizons
        ]

    def _restore(self, snap):
        for h, (top, bottom) in zip(self.horizons, snap):
            h.top_offsets = normalize_offsets(top)
            h.bottom_offsets = normalize_offsets(bottom)
        self._invalidate()

    def _push_undo(self):
        self._undo_stack.append(self._snapshot())
        del self._undo_stack[:-50]  # máximo 50 pasos

    def undo_shape(self):
        """Deshace la última edición de forma."""
        if not self._undo_stack:
            return
        self._restore(self._undo_stack.pop())
        self.shapeEdited.emit()

    def reset_shapes(self):
        """Elimina todas las formas manuales y vuelve a la forma automática."""
        if not self.has_shapes():
            return
        self._push_undo()
        for h in self.horizons:
            h.top_offsets = None
            h.bottom_offsets = None
        self._invalidate()
        self.shapeEdited.emit()

    def _invalidate(self):
        self._cached_paths = []
        self._cache_width = -1
        self.update()

    def _offsets_for(self, boundary_idx):
        """Lista de offsets (editable) del límite indicado; la crea si no existe."""
        if boundary_idx == 0:
            hor = self.horizons[0]
            if hor.top_offsets is None:
                hor.top_offsets = [0.0] * SHAPE_POINTS
            return hor.top_offsets
        hor = self.horizons[boundary_idx - 1]
        if hor.bottom_offsets is None:
            hor.bottom_offsets = [0.0] * SHAPE_POINTS
        return hor.bottom_offsets

    def _handle_positions(self):
        """[(límite, punto, QPointF)] en coordenadas del widget (con scroll)."""
        if not self._boundaries:
            return []
        out = []
        idxs = ProfileGeometry.control_indices()
        for b, pts in enumerate(self._boundaries):
            for k, i in enumerate(idxs):
                p = pts[i]
                out.append((b, k, QPointF(p.x(), p.y() + self._scroll_offset)))
        return out

    def _hit_test(self, pos):
        best, best_d = None, HANDLE_HIT_RADIUS
        for b, k, p in self._handle_positions():
            d = ((p.x() - pos.x()) ** 2 + (p.y() - pos.y()) ** 2) ** 0.5
            if d <= best_d:
                best, best_d = (b, k), d
        return best

    def _boundary_name(self, b):
        if b == 0:
            return f"Superficie ({self.horizons[0].name})"
        upper = self.horizons[b - 1].name
        if b < len(self.horizons):
            return f"Límite {upper} / {self.horizons[b].name}"
        return f"Base de {upper}"

    def mousePressEvent(self, event):
        if not (self.edit_mode and self.horizons):
            return super().mousePressEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        hit = self._hit_test(event.pos())
        if hit is None:
            return super().mousePressEvent(event)
        self._push_undo()
        b, k = hit
        offsets = self._offsets_for(b)
        self._drag = {
            "b": b,
            "k": k,
            "y0": event.pos().y(),
            "start": list(offsets),
            "whole": bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
        }
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        if not self.edit_mode:
            return super().mouseMoveEvent(event)
        if self._drag:
            d = self._drag
            delta_cm = (event.pos().y() - d["y0"]) / max(self._current_scale, 1e-6)
            offsets = self._offsets_for(d["b"])
            if d["whole"]:
                for i in range(SHAPE_POINTS):
                    offsets[i] = self._clamp(d["start"][i] + delta_cm)
            else:
                offsets[d["k"]] = self._clamp(d["start"][d["k"]] + delta_cm)
            self._cached_paths = []
            self._cache_width = -1
            self.update()
            event.accept()
            return
        hit = self._hit_test(event.pos())
        if hit != self._hover:
            self._hover = hit
            self.setCursor(
                Qt.CursorShape.SizeVerCursor if hit else Qt.CursorShape.CrossCursor
            )
            self.setToolTip(self._boundary_name(hit[0]) if hit else "")
            self.update()

    def mouseReleaseEvent(self, event):
        if self.edit_mode and self._drag:
            d = self._drag
            self._drag = None
            # Si no hubo cambio real, descartar el paso de deshacer
            if self._offsets_for(d["b"]) == d["start"]:
                if self._undo_stack:
                    self._undo_stack.pop()
                self._cleanup_empty()
            else:
                self._cleanup_empty()
                self.shapeEdited.emit()
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Doble clic sobre un punto: lo devuelve a la forma automática."""
        if not (self.edit_mode and self.horizons):
            return super().mouseDoubleClickEvent(event)
        hit = self._hit_test(event.pos())
        if hit is None:
            return super().mouseDoubleClickEvent(event)
        b, k = hit
        offsets = self._offsets_for(b)
        if offsets[k] != 0.0:
            self._push_undo()
            offsets[k] = 0.0
            self._cleanup_empty()
            self._invalidate()
            self.shapeEdited.emit()
        event.accept()

    @staticmethod
    def _clamp(v):
        return max(-MAX_SHAPE_OFFSET_CM, min(MAX_SHAPE_OFFSET_CM, v))

    def _cleanup_empty(self):
        """Convierte listas de offsets todo-cero en None (sin forma manual)."""
        for h in self.horizons:
            h.top_offsets = normalize_offsets(h.top_offsets)
            h.bottom_offsets = normalize_offsets(h.bottom_offsets)
        self._cached_paths = []
        self._cache_width = -1

    def _draw_edit_overlay(self, painter):
        """Dibuja los puntos de control y las líneas guía del modo lápiz."""
        if not self._boundaries:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active_b = (
            self._drag["b"] if self._drag else (self._hover[0] if self._hover else None)
        )
        for b, pts in enumerate(self._boundaries):
            if b == active_b:
                guide = QPainterPath(
                    QPointF(pts[0].x(), pts[0].y() + self._scroll_offset)
                )
                for p in pts[1:]:
                    guide.lineTo(QPointF(p.x(), p.y() + self._scroll_offset))
                painter.setPen(QPen(QColor(255, 140, 0, 220), 2.2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(guide)
        for b, k, p in self._handle_positions():
            active = (self._drag and (self._drag["b"], self._drag["k"]) == (b, k)) or (
                not self._drag and self._hover == (b, k)
            )
            whole = self._drag and self._drag["whole"] and self._drag["b"] == b
            painter.setPen(QPen(QColor(40, 40, 40), 1.2))
            painter.setBrush(
                QColor(255, 140, 0) if (active or whole) else QColor(255, 255, 255, 230)
            )
            r = HANDLE_RADIUS + (1.5 if active else 0)
            painter.drawEllipse(p, r, r)
        if self._drag:
            d = self._drag
            offsets = self._offsets_for(d["b"])
            val = offsets[d["k"]]
            text = f"{self._boundary_name(d['b'])}:  {val:+.1f} cm"
            if d["whole"]:
                text += "  (límite completo)"
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            w = metrics.horizontalAdvance(text) + 12
            box = QRectF(8, 8, w, metrics.height() + 8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(30, 30, 30, 200))
            painter.drawRoundedRect(box, 4, 4)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def _update_widget_height(self):
        """Ajusta la altura mínima del widget según la escala actual."""
        if self.horizons:
            max_depth = max(h.bottom for h in self.horizons)
            new_height = max(600, int(max_depth * self._current_scale) + 50)
            self.setMinimumHeight(new_height)
        else:
            self.setMinimumHeight(600)
        self.update()

    def set_data(self, horizons):
        if horizons is not self.horizons:
            self._undo_stack = []  # otro perfil: el historial ya no aplica
        self.horizons = horizons
        # Invalidar caché al cambiar datos
        self._cached_paths = []
        self._cache_width = -1
        self._hover = None
        self._drag = None
        self._scroll_offset = 0  # reset scroll al cambiar datos
        self._update_widget_height()

    def zoom_in(self):
        """Aumenta la escala (zoom in)."""
        self._current_scale = min(self._current_scale * 1.3, 50.0)
        self._cached_paths = []
        self._cache_width = -1
        self._update_widget_height()

    def zoom_out(self):
        """Reduce la escala (zoom out)."""
        self._current_scale = max(self._current_scale / 1.3, 0.3)
        self._cached_paths = []
        self._cache_width = -1
        self._update_widget_height()

    def zoom_reset(self):
        """Restablece la escala al valor por defecto."""
        self._current_scale = self.scale_factor
        self._scroll_offset = 0
        self._cached_paths = []
        self._cache_width = -1
        self._update_widget_height()

    def wheelEvent(self, event):
        """
        Maneja la rueda del mouse para hacer zoom en el canvas.
        Ctrl+rueda = zoom, Shift+rueda = scroll vertical.
        """
        modifiers = event.modifiers()
        delta = event.angleDelta().y()

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            # Zoom in/out
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            # Scroll horizontal (invertido para natural feel)
            self._scroll_offset += delta / 8
            self.update()
            event.accept()
        else:
            # Scroll vertical
            self._scroll_offset += delta / 8
            self.update()
            event.accept()

    def save_image(self, file_path):
        """Exporta el contenido actual del canvas a una imagen."""
        if not self.horizons:
            return False

        # Crear un pixmap con el tamaño actual del widget
        # Usamos el tamaño real del contenido dibujado
        max_depth = max(h.bottom for h in self.horizons)
        content_height = int(max_depth * self.scale_factor) + 50

        pixmap = QPixmap(self.width(), content_height)
        pixmap.fill(Qt.GlobalColor.white)  # Fondo blanco para la exportación

        # Usar un painter sobre el pixmap
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Forzar el redibujado sobre el pixmap
        self.render_to_painter(painter, self.width(), content_height)
        painter.end()
        return pixmap.save(file_path)

    def _build_geometry_cache(self, width):
        """Calcula y almacena los QPainterPath de cada horizonte.
        Usa _current_scale para el zoom.
        """
        self._cached_paths = []
        self._cache_width = width
        scale = self._current_scale

        # Geometría compartida con la vista previa y el PDF (incluye la forma
        # manual del lápiz y evita que los límites se crucen)
        self._boundaries = ProfileGeometry.compute_boundaries(
            self.horizons, width, scale
        )

        for i, hor in enumerate(self.horizons):
            top_b, bottom_b = self._boundaries[i], self._boundaries[i + 1]
            path = QPainterPath()
            path.moveTo(top_b[0])
            for p in top_b[1:]:
                path.lineTo(p)
            for p in reversed(bottom_b):
                path.lineTo(p)
            path.closeSubpath()

            self._cached_paths.append((path, hor))

    def render_to_painter(self, painter, width, height):
        """Lógica de renderizado compartida entre paintEvent y exportación.
        Usa el caché de geometría para que los límites sean siempre estáticos.
        """
        # Reconstruir caché solo si el ancho cambió o está vacío
        if not self._cached_paths or self._cache_width != width:
            self._build_geometry_cache(width)

        scale = self._current_scale

        painter.save()
        # Aplicar offset de scroll vertical
        painter.translate(0, self._scroll_offset)

        for path, hor in self._cached_paths:
            y_bottom = hor.bottom * scale
            grad_y_start = hor.top * scale
            grad_y_end = y_bottom
            grad = QLinearGradient(0, grad_y_start, 0, grad_y_end)
            grad.setColorAt(0, hor.color)
            grad.setColorAt(1, hor.color.darker(110))

            painter.save()
            painter.setClipPath(path)

            if hor.image_path and os.path.exists(hor.image_path):
                pixmap_img = QPixmap(hor.image_path)
                if not pixmap_img.isNull():
                    image_brush = QBrush(pixmap_img)
                    painter.setBrush(QBrush(grad))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawPath(path)
                    painter.setBrush(image_brush)
                    painter.drawPath(path)
                else:
                    painter.setBrush(QBrush(grad))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawPath(path)
            else:
                painter.setBrush(QBrush(grad))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPath(path)

            self.draw_soil_texture(painter, path, hor.texture)

            # Etiqueta del horizonte
            y_text = (hor.top * scale) + 10 - (hor.folding * 0.5)
            text_rect = QRectF(10, y_text, width - 20, 20)

            painter.setPen(Qt.GlobalColor.black)
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                hor.name,
            )
            painter.restore()

            painter.setPen(QPen(hor.color.darker(150), 1, Qt.PenStyle.SolidLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        if self.show_fault_line:
            painter.setPen(QPen(QColor(255, 0, 0, 180), 2, Qt.PenStyle.DashLine))
            center_x = width * 0.5
            for hor in self.horizons:
                if hor.fault_type != "none":
                    y_start = hor.top * scale
                    y_end = hor.bottom * scale
                    if hor.fault_type == "normal":
                        x1 = center_x + (y_start * 0.4)
                        x2 = center_x + (y_end * 0.4)
                    elif hor.fault_type == "inverse":
                        x1 = center_x - (y_start * 0.4)
                        x2 = center_x - (y_end * 0.4)
                    else:
                        continue
                    painter.drawLine(int(x1), int(y_start), int(x2), int(y_end))

        painter.restore()  # restaurar translate del scroll

    def paintEvent(self, event):
        if self._in_paint_event:
            return
        if not self.horizons:
            return

        self._in_paint_event = True
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.render_to_painter(painter, self.width(), self.height())
            if self.edit_mode:
                self._draw_edit_overlay(painter)
            painter.end()
        finally:
            self._in_paint_event = False

    def draw_soil_texture(self, painter, path, texture_type):
        """
        Dibuja texturas específicas para cada tipo de material.
        Las texturas ayudan a diferenciar visualmente los diferentes horizontes.
        """
        painter.setPen(QPen(QColor(0, 0, 0, 40), 1))
        rect = path.boundingRect()
        step = 8

        texture_lower = texture_type.lower()

        # Arena - puntos dispersos
        if "arena" in texture_lower or "sand" in texture_lower:
            for x in range(int(rect.left()), int(rect.right()), step):
                for y in range(int(rect.top()), int(rect.bottom()), step):
                    painter.drawPoint(x + (y % 4), y)

        # Arcilla - líneas diagonales
        elif "arcilla" in texture_lower or "clay" in texture_lower:
            for i in range(int(rect.left() - rect.height()), int(rect.right()), step):
                painter.drawLine(i, int(rect.top()), i + 20, int(rect.bottom()))

        # Limo - líneas onduladas horizontales
        elif "limo" in texture_lower or "silt" in texture_lower:
            for y in range(int(rect.top()), int(rect.bottom()), step):
                for x in range(int(rect.left()), int(rect.right()), step):
                    painter.drawPoint(x, y)

        # Franco - patrón de cruz
        elif "franco" in texture_lower or "loam" in texture_lower:
            for x in range(int(rect.left()) + step, int(rect.right()), step * 2):
                for y in range(int(rect.top()) + step, int(rect.bottom()), step * 2):
                    painter.drawLine(x - 3, y, x + 3, y)
                    painter.drawLine(x, y - 3, x, y + 3)

        # Grava - círculos pequeños
        elif "grava" in texture_lower or "gravel" in texture_lower:
            for x in range(int(rect.left()) + step, int(rect.right()), step * 2):
                for y in range(int(rect.top()) + step, int(rect.bottom()), step * 2):
                    painter.drawEllipse(x, y, 3, 3)

        # Roca - patrón de bloques
        elif "roca" in texture_lower or "rock" in texture_lower:
            for x in range(int(rect.left()), int(rect.right()), step * 3):
                for y in range(int(rect.top()), int(rect.bottom()), step * 2):
                    painter.drawRect(x, y, step * 2, step)

        # Materia orgánica / Turba - patrón denso de puntos
        elif (
            "orgánica" in texture_lower
            or "organic" in texture_lower
            or "turba" in texture_lower
            or "peat" in texture_lower
        ):
            for x in range(int(rect.left()), int(rect.right()), 4):
                for y in range(int(rect.top()), int(rect.bottom()), 4):
                    painter.drawPoint(x, y)

        # Caliza - bloques alternados (ladrillos)
        elif "caliza" in texture_lower:
            for y in range(int(rect.top()), int(rect.bottom()), step * 2):
                for x in range(int(rect.left()), int(rect.right()), step * 4):
                    # Desplazamiento tipo ladrillo
                    offset = (step * 2) if (y // (step * 2)) % 2 else 0
                    painter.drawRect(x + offset, y, step * 4, step * 2)

        # Yeso - pequeños cristales / líneas angulares
        elif "yeso" in texture_lower:
            for x in range(int(rect.left()), int(rect.right()), step * 2):
                for y in range(int(rect.top()), int(rect.bottom()), step * 2):
                    painter.drawLine(x, y, x + 3, y + 5)
                    painter.drawLine(x + 3, y + 5, x + 6, y)

        # Ceniza volcánica - "v" pequeñas dispersas
        elif "ceniza" in texture_lower:
            for x in range(int(rect.left()), int(rect.right()), step * 3):
                for y in range(int(rect.top()), int(rect.bottom()), step * 3):
                    painter.drawLine(x, y, x + 2, y + 3)
                    painter.drawLine(x + 2, y + 3, x + 4, y)

        # Esquisto / Laminado - líneas horizontales finas y densas
        elif "esquisto" in texture_lower:
            for y in range(int(rect.top()), int(rect.bottom()), 4):
                painter.drawLine(int(rect.left()), y, int(rect.right()), y)

        # Carbón - hachurado denso
        elif "carbón" in texture_lower or "carbon" in texture_lower:
            painter.setPen(QPen(QColor(0, 0, 0, 80), 1))
            for i in range(int(rect.left() - rect.height()), int(rect.right()), 4):
                painter.drawLine(i, int(rect.top()), i + 15, int(rect.bottom()))

        # Sal - pequeños cuadrados (cubos de sal)
        elif "sal" in texture_lower:
            for x in range(int(rect.left()), int(rect.right()), step * 3):
                for y in range(int(rect.top()), int(rect.bottom()), step * 3):
                    painter.drawRect(x, y, 4, 4)

        # Por defecto - patrón sutil de puntos
        else:
            for x in range(int(rect.left()), int(rect.right()), step):
                for y in range(int(rect.top()), int(rect.bottom()), step):
                    painter.drawPoint(x, y)
