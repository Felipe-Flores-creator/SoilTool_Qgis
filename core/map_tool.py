from qgis.gui import QgsMapToolIdentify
from qgis.core import QgsProject
from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtWidgets import QLabel
from qgis.PyQt.QtGui import QPixmap, QPainter, QPainterPath, QColor
from .horizon_manager import HorizonManager


class SoilMapTool(QgsMapToolIdentify):
    """Herramienta para seleccionar unidades de suelo en el mapa."""

    featureSelected = pyqtSignal(object)  # Señal que envía la entidad seleccionada

    def __init__(self, canvas):
        super(SoilMapTool, self).__init__(canvas)
        self.canvas = canvas
        self.target_layer = None
        self.setCursor(Qt.CrossCursor)

        # Etiqueta para la previsualización del perfil
        self.preview_label = QLabel(self.canvas)
        self.preview_label.setFixedSize(60, 60)
        self.preview_label.setAttribute(Qt.WA_TransparentForMouseEvents)
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
                event.x(), event.y(), [self.target_layer], self.TopDownAll
            )
        else:
            # Identificar en todas las capas vectoriales visibles
            found_features = self.identify(
                event.x(), event.y(), self.TopDownAll, self.VectorLayer
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
                event.x(), event.y(), [self.target_layer], self.TopDownAll
            )
        else:
            found_features = self.identify(
                event.x(), event.y(), self.TopDownAll, self.VectorLayer
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
            # Solo mover la etiqueta si es la misma entidad y ya estamos mostrando el perfil
            self.preview_label.move(event.x() + 15, event.y() + 15)
            return

        self.last_hovered_fid = feature.id()

        # Consultar si la entidad tiene un perfil
        _, _, horizons = HorizonManager.get_profile_data(feature, layer)
        if horizons:
            self._draw_profile_preview(horizons)
            self.preview_label.move(event.x() + 15, event.y() + 15)
            self.preview_label.show()
        else:
            self.preview_label.hide()

    def _draw_profile_preview(self, horizons):
        # Crear un pixmap transparente
        pixmap = QPixmap(60, 60)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # Fondo blanco semitransparente circular
        painter.setBrush(QColor(255, 255, 255, 180))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 60, 60)

        # Máscara circular para los horizontes
        path = QPainterPath()
        path.addEllipse(0, 0, 60, 60)
        painter.setClipPath(path)

        # Calcular profundidad total
        total_depth = max([h.bottom for h in horizons]) if horizons else 1
        if total_depth <= 0:
            total_depth = 1

        # Dibujar cada horizonte como un rectángulo
        for h in horizons:
            top_y = (h.top / total_depth) * 60
            bottom_y = (h.bottom / total_depth) * 60
            height = bottom_y - top_y
            painter.fillRect(0, int(top_y), 60, int(height), h.color)

        painter.setClipping(False)
        # Dibujar borde para delimitar el círculo
        painter.setPen(QColor(50, 50, 50))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(1, 1, 58, 58)  # 1 px hacia adentro

        painter.end()
        self.preview_label.setPixmap(pixmap)
