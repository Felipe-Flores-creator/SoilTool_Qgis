from qgis.gui import QgsMapToolIdentify
from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtWidgets import QLabel
from qgis.PyQt.QtCore import QPointF, QRectF
from qgis.PyQt.QtGui import QPixmap, QPainter, QPainterPath, QColor, QFont, QPen
from .horizon_manager import HorizonManager
from .soil_symbology import draw_profile_column


class SoilMapTool(QgsMapToolIdentify):
    """Herramienta para seleccionar unidades de suelo en el mapa."""

    featureSelected = pyqtSignal(object)  # Señal que envía la entidad seleccionada

    def __init__(self, canvas):
        super(SoilMapTool, self).__init__(canvas)
        self.canvas = canvas
        self.target_layer = None
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Etiqueta para la previsualización del perfil
        self.preview_label = QLabel(self.canvas)
        self.preview_label.setFixedSize(210, 206)
        self.preview_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.preview_label.hide()
        self.last_hovered_fid = None

    def set_target_layer(self, layer):
        self.target_layer = layer

    def activate(self):
        super(SoilMapTool, self).activate()
        self.preview_label.hide()
        self.last_hovered_fid = None

    def deactivate(self):
        super(SoilMapTool, self).deactivate()
        self.preview_label.hide()

    def canvasReleaseEvent(self, event):
        # Identificar entidades
        if self.target_layer:
            # Si hay capa objetivo, identificar solo en ella para mayor precisión
            found_features = self.identify(
                event.pos().x(), event.pos().y(), [self.target_layer], self.TopDownAll
            )
        else:
            # Identificar en todas las capas vectoriales visibles
            found_features = self.identify(
                event.pos().x(), event.pos().y(), self.TopDownAll, self.VectorLayer
            )

        if not found_features:
            return

        # Seleccionar la primera entidad válida
        res = found_features[0]
        layer = res.mLayer

        # Validar que la capa sea vectorial (tenga getFeature)
        if not hasattr(layer, "getFeature"):
            return

        # Obtener la entidad fresca de la capa para asegurar atributos actualizados
        feature = layer.getFeature(res.mFeature.id())

        # Efecto visual de flash para confirmar selección (similar a QGIS/ArcGIS)
        self.canvas.flashFeatureIds(layer, [feature.id()])

        # Emitir señal con la entidad encontrada
        self.featureSelected.emit({"feature": feature, "layer": layer})

    def canvasMoveEvent(self, event):
        # Identificar entidades al mover el mouse (hover)
        if self.target_layer:
            found_features = self.identify(
                event.pos().x(), event.pos().y(), [self.target_layer], self.TopDownAll
            )
        else:
            found_features = self.identify(
                event.pos().x(), event.pos().y(), self.TopDownAll, self.VectorLayer
            )

        if not found_features:
            self.preview_label.hide()
            self.last_hovered_fid = None
            return

        res = found_features[0]
        layer = res.mLayer

        # Validar que la capa sea vectorial (tenga getFeature) antes de procesar
        if not hasattr(layer, "getFeature"):
            self.preview_label.hide()
            self.last_hovered_fid = None
            return

        feature = layer.getFeature(res.mFeature.id())

        if self.last_hovered_fid == feature.id() and self.preview_label.isVisible():
            # Solo mover la etiqueta si es la misma entidad y ya estamos
            # mostrando el perfil
            self._place_preview(event.pos())
            return

        self.last_hovered_fid = feature.id()

        # Consultar si la entidad tiene un perfil
        profile_id, _, horizons = HorizonManager.get_profile_data(feature, layer)
        if horizons:
            self._draw_profile_preview(horizons, profile_id)
            self._place_preview(event.pos())
            self.preview_label.show()
            self.preview_label.raise_()
        else:
            self.preview_label.hide()

    def _place_preview(self, pos):
        """Ubica la tarjeta junto al cursor sin salirse del mapa."""
        w, h = self.preview_label.width(), self.preview_label.height()
        x, y = pos.x() + 18, pos.y() + 18
        if x + w > self.canvas.width():
            x = pos.x() - w - 12
        if y + h > self.canvas.height():
            y = max(0, self.canvas.height() - h - 4)
        self.preview_label.move(max(0, x), max(0, y))

    def _draw_profile_preview(self, horizons, profile_id=None):
        """Tarjeta con un miniperfil rectangular (columna de suelo hacia abajo)."""
        horizons = sorted(horizons, key=lambda h: h.top)
        total = max(h.bottom for h in horizons) or 1.0

        W, COL_TOP, COL_H, PAD = 210, 30, 150, 8
        H = COL_TOP + COL_H + 26
        dpr = (
            self.canvas.devicePixelRatioF()
            if hasattr(self.canvas, "devicePixelRatioF")
            else 1.0
        )
        pixmap = QPixmap(int(W * dpr), int(H * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Sombra y tarjeta
        card = QRectF(2, 2, W - 6, H - 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 55))
        painter.drawRoundedRect(card.translated(3, 3), 7, 7)
        painter.setBrush(QColor(255, 255, 255, 245))
        painter.setPen(QPen(QColor("#8d6e63"), 1))
        painter.drawRoundedRect(card, 7, 7)

        # Encabezado
        header = QRectF(card.left(), card.top(), card.width(), 22)
        path = QPainterPath()
        path.addRoundedRect(header, 7, 7)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(path, QColor("#5d4037"))
        painter.fillRect(
            QRectF(header.left(), header.top() + 10, header.width(), 12),
            QColor("#5d4037"),
        )
        font = QFont()
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        title = f"Perfil {profile_id}" if profile_id not in (None, -1, "") else "Perfil"
        painter.drawText(
            header.adjusted(PAD, 0, -PAD, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title,
        )

        # Columna rectangular con regla de profundidad
        col_rect = QRectF(PAD, COL_TOP, 66, COL_H)
        draw_profile_column(
            painter,
            col_rect,
            horizons,
            unit=1.0,
            shaped=False,
            labels=False,
            ruler=True,
            ruler_width=24,
            font_px=8,
        )

        # Etiquetas a la derecha (con guía si deben desplazarse)
        col_right = col_rect.right()
        lx = col_right + 10
        scale = COL_H / total
        name_font = QFont()
        name_font.setPixelSize(10)
        name_font.setBold(True)
        depth_font = QFont()
        depth_font.setPixelSize(9)
        min_gap = 22
        last_y = COL_TOP - min_gap
        max_labels = int(COL_H / min_gap) + 1
        for i, h in enumerate(horizons[:max_labels]):
            mid = COL_TOP + ((h.top + h.bottom) / 2) * scale
            y = max(mid, last_y + min_gap)
            y = min(y, COL_TOP + COL_H - 6)
            last_y = y
            painter.setPen(QPen(QColor(120, 120, 120), 0.8))
            painter.drawLine(QPointF(col_right + 1, mid), QPointF(lx - 3, y))
            sw = QRectF(lx, y - 9, 8, 8)
            painter.fillRect(sw, h.color)
            painter.setPen(QPen(QColor(60, 60, 60), 0.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(sw)
            painter.setFont(name_font)
            painter.setPen(QColor(33, 33, 33))
            fm = painter.fontMetrics()
            name = fm.elidedText(h.name, Qt.TextElideMode.ElideRight, int(W - lx - 26))
            painter.drawText(QPointF(lx + 11, y - 1), name)
            painter.setFont(depth_font)
            painter.setPen(QColor(90, 90, 90))
            painter.drawText(
                QPointF(lx + 11, y + 10),
                f"{h.top:g}–{h.bottom:g} cm · {h.texture}"[:28],
            )
        if len(horizons) > max_labels:
            painter.setFont(depth_font)
            painter.drawText(
                QPointF(lx, COL_TOP + COL_H), f"+{len(horizons) - max_labels} más"
            )

        # Pie
        painter.setFont(depth_font)
        painter.setPen(QColor(90, 90, 90))
        painter.drawText(
            QRectF(PAD, COL_TOP + COL_H + 4, W - 2 * PAD, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"Prof. total {total:g} cm · {len(horizons)} horizontes",
        )

        painter.end()
        self.preview_label.setFixedSize(W, H)
        self.preview_label.setPixmap(pixmap)
