# -*- coding: utf-8 -*-
"""
Herramienta de mapa para dibujar perfiles topográficos sobre DEM.
Permite al usuario dibujar una línea poligonal con clics del mouse.
Al finalizar (doble clic / clic derecho), se activa el motor DEM.
"""

from qgis.gui import QgsMapTool
from qgis.core import (
    QgsPointXY,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
)
from qgis.PyQt.QtCore import pyqtSignal, Qt, QTimer
from qgis.PyQt.QtGui import QColor, QPen, QPainter
from qgis.PyQt.QtWidgets import (
    QMessageBox,
    QApplication,
)


class ProfileMapTool(QgsMapTool):
    """
    Herramienta de mapa para dibujar una polilínea sobre el DEM.
    Cada clic izquierdo añade un punto. Doble clic o clic derecho finaliza.
    Al terminar, emite la señal profileComplete con los datos generados.
    """

    profileComplete = pyqtSignal(object)  # Emite DEMProfileData
    drawingStarted = pyqtSignal()
    pointAdded = pyqtSignal(int)

    def __init__(self, canvas, raster_layer=None, vector_layers=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.raster_layer = raster_layer
        self.vector_layers = vector_layers or []

        self.points = []
        self.is_drawing = False
        self.rubber_band = None
        self.temp_rubber_band = None

        self.line_color = QColor(255, 0, 0, 200)
        self.line_width = 2

        self.setCursor(Qt.CrossCursor)

        # Bandera para evitar recursión de paint events durante actualización de rubber bands
        self._updating_rubber_band = False

    def set_raster_layer(self, layer):
        self.raster_layer = layer

    def set_vector_layers(self, layers):
        if layers is not None:
            self.vector_layers = layers

    def add_vector_layer(self, layer):
        if layer and layer not in self.vector_layers:
            self.vector_layers.append(layer)

    def _get_valid_vector_layers(self):
        valid_layers = []
        for layer in self.vector_layers:
            try:
                if layer and layer.isValid():
                    valid_layers.append(layer)
            except RuntimeError:
                pass
        return valid_layers

    def activate(self):
        super().activate()
        self.points = []
        self.is_drawing = False

        if not self.rubber_band:
            from qgis.gui import QgsRubberBand

            self.rubber_band = QgsRubberBand(self.canvas)
            self.rubber_band.setColor(self.line_color)
            self.rubber_band.setWidth(self.line_width)
            self.rubber_band.setIconSize(8)

        if not self.temp_rubber_band:
            from qgis.gui import QgsRubberBand

            self.temp_rubber_band = QgsRubberBand(self.canvas)
            self.temp_rubber_band.setColor(QColor(255, 0, 0, 100))
            self.temp_rubber_band.setWidth(1)
            self.temp_rubber_band.setIconSize(5)

        self.rubber_band.reset()
        self.temp_rubber_band.reset()

    def deactivate(self):
        super().deactivate()
        if self.rubber_band:
            self.rubber_band.reset()
        if self.temp_rubber_band:
            self.temp_rubber_band.reset()
        self.points = []
        self.is_drawing = False

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            map_point = self.toMapCoordinates(event.pos())

            if not self.is_drawing:
                self.is_drawing = True
                self.points = [map_point]
                self.rubber_band.reset()
                self.rubber_band.addPoint(map_point)
                self.rubber_band.show()
                self.drawingStarted.emit()
                self.pointAdded.emit(len(self.points))
            else:
                self.points.append(map_point)
                self.rubber_band.addPoint(map_point)
                self.pointAdded.emit(len(self.points))

        elif event.button() == Qt.RightButton:
            if self.is_drawing:
                self.finish_profile()

    def canvasDoubleClickEvent(self, event):
        if self.is_drawing:
            self.finish_profile()

    def canvasMoveEvent(self, event):
        if self.is_drawing and self.points and not self._updating_rubber_band:
            self._updating_rubber_band = True
            try:
                map_point = self.toMapCoordinates(event.pos())
                self.temp_rubber_band.reset()
                for pt in self.points:
                    self.temp_rubber_band.addPoint(pt)
                self.temp_rubber_band.addPoint(map_point)
                self.temp_rubber_band.show()
            finally:
                self._updating_rubber_band = False

    def _show_error_dialog(self, title, message, detailed_text=None):
        """Muestra un diálogo de error simple. Sin código basura."""
        msg = QMessageBox(self.canvas)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle(title)
        msg.setText(message)
        if detailed_text:
            msg.setDetailedText(detailed_text)
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Help)
        result = msg.exec_()

        if result == QMessageBox.Help and detailed_text:
            try:
                clipboard = QApplication.clipboard()
                clipboard.setText(detailed_text)
            except Exception:
                pass
            print("=" * 60)
            print(f"DIAGNÓSTICO ({title}) - copiado al portapapeles:")
            print("=" * 60)
            print(detailed_text)
            print("=" * 60)

    def finish_profile(self):
        if not self.is_drawing:
            self.deactivate()
            return

        if len(self.points) < 2:
            QMessageBox.warning(
                self.canvas,
                "Perfil DEM",
                "Debe dibujar al menos 2 puntos para generar un perfil.",
            )
            self.deactivate()
            return

        # Ocultar rubber bands
        if self.rubber_band:
            self.rubber_band.reset()
        if self.temp_rubber_band:
            self.temp_rubber_band.reset()

        # Verificar raster
        if not self.raster_layer or not isinstance(self.raster_layer, QgsRasterLayer):
            QMessageBox.warning(
                self.canvas,
                "Perfil DEM",
                "No hay una capa raster DEM seleccionada.\n"
                "Seleccione un TIFF DEM en el panel de Perfil Topográfico.",
            )
            self.deactivate()
            return

        profile_data = None
        try:
            from .dem_profile_engine import DEMProfileEngine, DEMProfileData

            valid_vector_layers = self._get_valid_vector_layers()
            if not valid_vector_layers:
                valid_vector_layers = None

            map_crs = self.canvas.mapSettings().destinationCrs()

            profile_data = DEMProfileEngine.generate_profile(
                raster_layer=self.raster_layer,
                polyline_points=self.points,
                vector_layers=valid_vector_layers,
                num_samples=DEMProfileEngine.DEFAULT_SAMPLE_POINTS,
                map_crs=map_crs,
            )

            if not profile_data.points:
                diagnostic_summary = (
                    profile_data.diagnostic.get_summary()
                    if hasattr(profile_data, "diagnostic")
                    else ""
                )

                self._show_error_dialog(
                    "Perfil DEM - Error de muestreo",
                    "No se pudieron muestrear puntos del DEM.\n\n"
                    "Posibles causas:\n"
                    "• El raster DEM y la línea están en diferentes CRS\n"
                    "• La línea no se superpone realmente con la extensión del raster\n"
                    "• El raster DEM tiene valores NoData en la zona de la línea\n"
                    "• El raster DEM no es válido o está corrupto\n"
                    "• Problemas de transformación de coordenadas",
                    detailed_text=diagnostic_summary if diagnostic_summary else None,
                )
                self.deactivate()
                return

            # Éxito: emitir señal DIFERIDA para evitar crashes de Qt/QtGui
            # cuando el tool aún está en medio de manejar eventos del mouse.
            self.is_drawing = False

            def _emit_profile_complete():
                try:
                    self.profileComplete.emit(profile_data)
                except Exception:
                    # No romper el flujo del tool por un fallo al emitir.
                    pass

            QTimer.singleShot(0, _emit_profile_complete)

        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            print(f"ERROR en ProfileMapTool.finish_profile:\n{tb}")

            diag_msg = ""
            try:
                if profile_data and hasattr(profile_data, "diagnostic"):
                    diag_msg = profile_data.diagnostic.get_summary()
            except Exception:
                pass

            self._show_error_dialog(
                "Error al generar perfil DEM",
                str(e),
                detailed_text=f"{tb}\n\n{diag_msg}" if diag_msg else tb,
            )
        finally:
            self.is_drawing = False
            self.deactivate()

    def cancel_drawing(self):
        self.is_drawing = False
        if self.rubber_band:
            self.rubber_band.reset()
        if self.temp_rubber_band:
            self.temp_rubber_band.reset()
        self.points = []
        self.deactivate()
