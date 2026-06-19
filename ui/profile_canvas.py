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
from qgis.PyQt.QtCore import Qt, QRectF
from ..core.profile_engine import ProfileGeometry


class EdafoCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.horizons = []
        self.setMinimumSize(300, 600)
        self.scale_factor = 3  # 1 cm = 3 pixels (base, usado en exportación)
        self._current_scale = 3.0  # escala actual (modificable con zoom)
        self.show_fault_line = False  # Control de visibilidad del plano de falla
        # Caché de geometría: se calcula una vez y se reutiliza en cada paintEvent
        self._cached_paths = []  # lista de (QPainterPath, HorizonData)
        self._cache_width = -1  # ancho con el que se calculó el caché
        # Bandera para evitar recursión de paint events
        self._in_paint_event = False
        # Offset vertical de scroll (para panorámica con arrastre)
        self._scroll_offset = 0

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
        self.horizons = horizons
        # Invalidar caché al cambiar datos
        self._cached_paths = []
        self._cache_width = -1
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

        if modifiers & Qt.ControlModifier:
            # Zoom in/out
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        elif modifiers & Qt.ShiftModifier:
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
        pixmap.fill(Qt.white)  # Fondo blanco para la exportación

        # Usar un painter sobre el pixmap
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # Forzar el redibujado sobre el pixmap
        self.render_to_painter(painter, self.width(), content_height)
        return pixmap.save(file_path)

    def _build_geometry_cache(self, width):
        """Calcula y almacena los QPainterPath de cada horizonte.
        Usa _current_scale para el zoom.
        """
        self._cached_paths = []
        self._cache_width = width
        scale = self._current_scale

        h0 = self.horizons[0]
        # El primer horizonte usa la misma amplitud de su boundary_type para que
        # su borde superior no sea completamente plano comparado con los demás
        top_amp = {"abrupt": 2, "clear": 5, "gradual": 12, "diffuse": 25}.get(
            h0.boundary_type, 5
        )
        current_top_boundary = ProfileGeometry.generate_boundary(
            0,
            width,
            amplitude=top_amp,
            folding=h0.folding,
            fault_type="none",
            fault_displacement=0,
            inclination=getattr(h0, "inclination", 0),
        )

        for hor in self.horizons:
            y_bottom = hor.bottom * scale
            amp = {"abrupt": 2, "clear": 5, "gradual": 12, "diffuse": 25}.get(
                hor.boundary_type, 5
            )

            bottom_boundary = ProfileGeometry.generate_boundary(
                y_bottom,
                width,
                amplitude=amp,
                folding=hor.folding,
                fault_type=hor.fault_type,
                fault_displacement=hor.fault_displacement,
                inclination=getattr(hor, "inclination", 0),
            )

            path = QPainterPath()
            path.moveTo(current_top_boundary[0])
            for p in current_top_boundary[1:]:
                path.lineTo(p)
            for p in reversed(bottom_boundary):
                path.lineTo(p)
            path.closeSubpath()

            self._cached_paths.append((path, hor))
            current_top_boundary = bottom_boundary

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
                    painter.setPen(Qt.NoPen)
                    painter.drawPath(path)
                    painter.setBrush(image_brush)
                    painter.drawPath(path)
                else:
                    painter.setBrush(QBrush(grad))
                    painter.setPen(Qt.NoPen)
                    painter.drawPath(path)
            else:
                painter.setBrush(QBrush(grad))
                painter.setPen(Qt.NoPen)
                painter.drawPath(path)

            self.draw_soil_texture(painter, path, hor.texture)

            # Etiqueta del horizonte
            y_text = (hor.top * scale) + 10 - (hor.folding * 0.5)
            text_rect = QRectF(10, y_text, width - 20, 20)

            painter.setPen(Qt.black)
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, hor.name)
            painter.restore()

            painter.setPen(QPen(hor.color.darker(150), 1, Qt.SolidLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

        if self.show_fault_line:
            painter.setPen(QPen(QColor(255, 0, 0, 180), 2, Qt.DashLine))
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
            painter.setRenderHint(QPainter.Antialiasing)
            self.render_to_painter(painter, self.width(), self.height())
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
