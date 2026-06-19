# -*- coding: utf-8 -*-
"""
Panel Dock de Perfil Topográfico Dinámico con Matplotlib.
Permite visualizar la topografía y las capas edafológicas intersectadas en tiempo real.
Incluye localizador espacial: al mover el mouse sobre el perfil, se marca la posición
en el mapa QGIS; al hacer zoom, se sombrea el tramo visible del perfil.
"""

from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QDoubleSpinBox,
    QSizePolicy,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.gui import QgsMapLayerComboBox, QgsRubberBand
from qgis.core import (
    QgsMapLayerProxyModel,
    QgsProject,
    QgsGeometry,
    QgsPointXY,
    QgsCoordinateTransform,
)
from qgis.PyQt.QtGui import QColor


import matplotlib

matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

from ..core.dynamic_profile_engine import DynamicProfileEngine


class DynamicProfileDock(QDockWidget):
    """QDockWidget inferior para renderizar perfiles dinámicos con Matplotlib."""

    def __init__(self, parent=None, iface=None):
        super().__init__("SoilTool - Perfil Topográfico Dinámico (Matplotlib)", parent)
        self.iface = iface
        self.points_data = []
        self.line_geometry = None
        self.map_crs = None
        self.setAllowedAreas(Qt.TopDockWidgetArea | Qt.BottomDockWidgetArea)
        self.setMinimumHeight(280)

        # --- Marcadores espaciales en el mapa ---
        self.position_marker = None  # QgsRubberBand para punto indicador
        self.view_extent_band = None  # QgsRubberBand para área visible
        self._connection_active = False  # evita bucles de actualización

        self.setup_ui()

    def setup_ui(self):
        # Widget contenedor principal
        self.main_widget = QWidget()
        self.layout = QVBoxLayout(self.main_widget)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(4)

        # Panel de control superior
        self.control_layout = QHBoxLayout()
        self.control_layout.setSpacing(10)

        # Selección de DEM
        self.control_layout.addWidget(QLabel("DEM:"))
        self.dem_combo = QgsMapLayerComboBox()
        self.dem_combo.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.dem_combo.setFixedWidth(140)
        self.control_layout.addWidget(self.dem_combo)

        # Selección de Capa Edafológica
        self.control_layout.addWidget(QLabel("Capa de Suelos:"))
        self.soils_combo = QgsMapLayerComboBox()
        self.soils_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.soils_combo.setFixedWidth(140)
        self.control_layout.addWidget(self.soils_combo)

        # Selector de unidad de distancia
        self.control_layout.addWidget(QLabel("Unidad:"))
        from qgis.PyQt.QtWidgets import QComboBox

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["Metros (m)", "Centímetros (cm)"])
        self.unit_combo.setFixedWidth(120)
        self.unit_combo.currentIndexChanged.connect(self.on_unit_changed)
        self.control_layout.addWidget(self.unit_combo)

        # Paso de muestreo
        self.control_layout.addWidget(QLabel("Paso Muestreo (m):"))
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(1.0, 500.0)
        self.step_spin.setValue(5.0)
        self.step_spin.setSingleStep(1.0)
        self.step_spin.setFixedWidth(70)
        self.control_layout.addWidget(self.step_spin)

        # Botón para dibujar perfil
        self.draw_btn = QPushButton("✏️ Trazar Perfil")
        self.draw_btn.setCheckable(True)
        self.draw_btn.setStyleSheet(
            "font-weight: bold; background-color: #3498db; color: white;"
        )
        self.draw_btn.clicked.connect(self.toggle_draw_tool)
        self.control_layout.addWidget(self.draw_btn)

        self.control_layout.addStretch()
        self.layout.addLayout(self.control_layout)

        # Canvas de Matplotlib
        self.figure = Figure(tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.layout.addWidget(self.canvas, 1)

        # Barra de herramientas de Matplotlib
        self.toolbar = NavigationToolbar(self.canvas, self.main_widget)
        self.toolbar.pan()
        self.layout.addWidget(self.toolbar)

        self.setWidget(self.main_widget)

        # Conectar eventos de mouse de Matplotlib para localización espacial
        self.canvas.mpl_connect("motion_notify_event", self._on_plot_mouse_move)
        self.canvas.mpl_connect("draw_event", self._on_plot_redraw)
        # Conectar la señal de navegación (zoom/pan) para actualizar el área visible
        self.toolbar._actions_triggered = []  # para prevenir errores
        self.toolbar._nav_stack  # forzar inicialización del stack
        try:
            self.toolbar._connected = True
        except Exception:
            pass

    def _init_rubber_bands(self):
        """Inicializa las bandas de goma en el canvas de QGIS si es necesario."""
        if not self.iface:
            return
        canvas = self.iface.mapCanvas()
        if self.position_marker is None:
            self.position_marker = QgsRubberBand(canvas)
            self.position_marker.setColor(QColor(255, 0, 0, 200))
            self.position_marker.setWidth(4)
            self.position_marker.setIconSize(12)
        if self.view_extent_band is None:
            self.view_extent_band = QgsRubberBand(canvas)
            self.view_extent_band.setColor(QColor(0, 150, 255, 30))
            self.view_extent_band.setWidth(2)

    def clear_spatial_markers(self):
        """Limpia los marcadores espaciales del mapa."""
        if self.position_marker:
            try:
                self.position_marker.reset()
            except RuntimeError:
                self.position_marker = None
        if self.view_extent_band:
            try:
                self.view_extent_band.reset()
            except RuntimeError:
                self.view_extent_band = None

    def toggle_draw_tool(self, checked):
        """Activa o desactiva la herramienta de mapa para trazar el perfil."""
        if not self.iface:
            return

        if checked:
            from ..core.profile_map_tool import ProfileMapTool

            # Crear y establecer la herramienta de perfil
            dem_layer = self.dem_combo.currentLayer()
            soils_layer = self.soils_combo.currentLayer()

            # Instanciar el ProfileMapTool original pero interceptar su finalización
            self.map_tool = ProfileMapTool(self.iface.mapCanvas(), dem_layer)
            if soils_layer:
                self.map_tool.add_vector_layer(soils_layer)

            self.map_tool.profileComplete.connect(self.on_profile_drawn)
            self.iface.mapCanvas().setMapTool(self.map_tool)
        else:
            self.deactivate_tool()

    def deactivate_tool(self):
        if self.iface:
            canvas = self.iface.mapCanvas()
            current_tool = canvas.mapTool()
            if hasattr(self, "map_tool") and current_tool == self.map_tool:
                canvas.unsetMapTool(self.map_tool)
                self.map_tool.cancel_drawing()
        self.draw_btn.blockSignals(True)
        self.draw_btn.setChecked(False)
        self.draw_btn.blockSignals(False)

    def on_profile_drawn(self, dem_profile_data):
        """Manejador al terminar el trazo de la línea de perfil."""
        self.deactivate_tool()

        # Limpiar marcadores anteriores
        self.clear_spatial_markers()

        # Recuperamos la geometría trazada
        if not dem_profile_data or not dem_profile_data.polyline:
            return

        self.line_geometry = QgsGeometry.fromPolylineXY(dem_profile_data.polyline)
        dem_layer = self.dem_combo.currentLayer()
        soils_layer = self.soils_combo.currentLayer()
        step_size = self.step_spin.value()
        self.map_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

        # Generar perfil dinámico
        self.points_data = DynamicProfileEngine.generate_dynamic_profile(
            dem_layer=dem_layer,
            soils_layer=soils_layer,
            line_geometry=self.line_geometry,
            step_size=step_size,
            map_crs=self.map_crs,
        )

        self.plot_profile()

    def _interpolate_point_on_line(self, distance):
        """
        Interpola un punto (QgsPointXY) a lo largo de self.line_geometry
        a la distancia dada (en metros, mismo CRS que la línea).
        Retorna None si no es posible.
        """
        if not self.line_geometry or self.line_geometry.isEmpty():
            return None
        try:
            pt_geom = self.line_geometry.interpolate(distance)
            if pt_geom and not pt_geom.isEmpty():
                return pt_geom.asPoint()
        except Exception:
            pass
        return None

    def _update_position_marker(self, distance):
        """Actualiza el marcador de posición en el mapa a la distancia dada."""
        if not self.iface:
            return
        self._init_rubber_bands()
        if self.position_marker is None:
            return

        pt = self._interpolate_point_on_line(distance)
        if pt is None:
            self.position_marker.reset()
            return

        try:
            self.position_marker.reset()
            self.position_marker.addPoint(pt)
            self.position_marker.show()
        except RuntimeError:
            pass

    def _update_view_extent(self, x_min, x_max):
        """
        Sombrea en el mapa el tramo del perfil que corresponde
        al rango visible en el plot (x_min, x_max en distancia).
        """
        if not self.iface or not self.line_geometry:
            return
        self._init_rubber_bands()
        if self.view_extent_band is None:
            return

        try:
            self.view_extent_band.reset()
        except RuntimeError:
            self.view_extent_band = None
            return

        # Extraer los puntos de la línea original que caen dentro del rango visible
        if not self.points_data:
            return

        # Buscar puntos dentro del rango
        visible_pts = []
        for pt_data in self.points_data:
            d = pt_data["distance"]
            if x_min <= d <= x_max:
                map_pt = self._interpolate_point_on_line(d)
                if map_pt:
                    visible_pts.append(map_pt)
                else:
                    # Si no podemos interpolar exactamente, usar coordenadas guardadas
                    visible_pts.append(QgsPointXY(pt_data["x"], pt_data["y"]))

        if len(visible_pts) < 2:
            # Si hay muy pocos puntos, dibujar un segmento desde x_min a x_max
            p1 = self._interpolate_point_on_line(x_min)
            p2 = self._interpolate_point_on_line(x_max)
            if p1 and p2:
                visible_pts = [p1, p2]

        if len(visible_pts) >= 2:
            try:
                for p in visible_pts:
                    self.view_extent_band.addPoint(p)
                self.view_extent_band.setWidth(3)
                self.view_extent_band.show()
            except RuntimeError:
                pass

    def _get_scale_factor(self):
        """Retorna el factor de escala actual (1.0 para metros, 100.0 para cm)."""
        return (
            100.0
            if hasattr(self, "unit_combo") and self.unit_combo.currentIndex() == 1
            else 1.0
        )

    def _on_plot_mouse_move(self, event):
        """
        Evento de movimiento del mouse sobre el plot de Matplotlib.
        Actualiza el marcador de posición en el mapa QGIS.
        """
        if not self.points_data or not event.inaxes:
            return

        # Obtener distancia (eje X) en la posición del mouse
        x_data = event.xdata
        if x_data is None:
            return

        # Convertir a metros si está en cm
        scale = self._get_scale_factor()
        distance_m = x_data / scale if scale > 0 else x_data
        self._update_position_marker(distance_m)

    def _on_plot_redraw(self, event):
        """
        Evento de redibujo del plot (zoom, pan, etc).
        Actualiza el área visible en el mapa QGIS.
        """
        if not self.points_data:
            return

        try:
            ax = self.figure.axes[0]
            x_min, x_max = ax.get_xlim()
            # Convertir a metros si está en cm
            scale = self._get_scale_factor()
            x_min_m = x_min / scale if scale > 0 else x_min
            x_max_m = x_max / scale if scale > 0 else x_max
            self._update_view_extent(x_min_m, x_max_m)
        except (IndexError, Exception):
            pass

    def on_unit_changed(self, index):
        """Cambia la unidad de visualización del eje de distancia."""
        if self.points_data:
            self.plot_profile()

    def plot_profile(self):
        """Dibuja el perfil y los estratos en el canvas de Matplotlib."""
        self.figure.clear()

        if not self.points_data:
            self.canvas.draw()
            return

        ax = self.figure.add_subplot(111)

        distances = [pt["distance"] for pt in self.points_data]
        elevations = [pt["z"] for pt in self.points_data]

        # Determinar unidad de visualización
        use_cm = self.unit_combo.currentIndex() == 1
        scale = 100.0 if use_cm else 1.0
        unit_label = "cm" if use_cm else "m"

        # Escalar distancias si está en cm
        plot_distances = [d * scale for d in distances]

        # Graficar terreno natural - color amarillo fuerte
        ax.plot(
            plot_distances,
            elevations,
            color="#FFD700",
            label="Terreno (DEM)",
            linewidth=2.5,
        )

        # Graficar estratos edafológicos segmentados
        # Para cada segmento entre i e i+1, dibujamos las capas edafológicas correspondientes
        for idx in range(len(self.points_data) - 1):
            pt1 = self.points_data[idx]
            pt2 = self.points_data[idx + 1]

            # Escalar x_seg según la unidad
            x_seg = [pt1["distance"] * scale, pt2["distance"] * scale]
            z_seg = [pt1["z"], pt2["z"]]

            horizons1 = pt1["horizons"] or []
            horizons2 = pt2["horizons"] or []

            # Encontrar el número máximo de horizontes
            max_hor = max(len(horizons1), len(horizons2))

            prev_bottom1 = 0.0
            prev_bottom2 = 0.0

            for h_idx in range(max_hor):
                h1 = horizons1[h_idx] if h_idx < len(horizons1) else None
                h2 = horizons2[h_idx] if h_idx < len(horizons2) else None

                # Límites superiores en metros de profundidad (convertidos de cm)
                top1 = h1.top / 100.0 if h1 else prev_bottom1
                top2 = h2.top / 100.0 if h2 else prev_bottom2

                # Límites inferiores
                bottom1 = h1.bottom / 100.0 if h1 else top1
                bottom2 = h2.bottom / 100.0 if h2 else top2

                # Convertir a elevaciones absolutas
                y1 = [pt1["z"] - top1, pt2["z"] - top2]
                y2 = [pt1["z"] - bottom1, pt2["z"] - bottom2]

                # Obtener color y nombre para la leyenda
                color = "#d2b48c"
                label = "Estrato edafológico"
                if h1:
                    color = (
                        h1.color.name() if hasattr(h1.color, "name") else str(h1.color)
                    )
                    label = h1.name
                elif h2:
                    color = (
                        h2.color.name() if hasattr(h2.color, "name") else str(h2.color)
                    )
                    label = h2.name

                # Relleno del estrato - borde con el color del estrato en lugar de negro
                ax.fill_between(
                    x_seg,
                    y1,
                    y2,
                    color=color,
                    alpha=0.8,
                    edgecolor=color,
                    linewidth=0.3,
                )

                prev_bottom1 = bottom1
                prev_bottom2 = bottom2

        # Detalles del gráfico
        ax.set_title("Perfil Topográfico Dinámico y Estratigrafía Edafológica")
        ax.set_xlabel(f"Distancia ({unit_label})")
        ax.set_ylabel("Elevación (m s.n.m.)")
        ax.grid(True, linestyle="--", alpha=0.6)

        # Leyenda única (sin duplicados)
        handles, labels = ax.get_legend_handles_labels()
        by_label = dict(zip(labels, handles))

        # Agregar parches manuales a la leyenda para los horizontes edafológicos dibujados
        import matplotlib.patches as mpatches

        seen_horizons = {}
        for pt in self.points_data:
            for h in pt["horizons"] or []:
                if h.name not in seen_horizons:
                    color_val = (
                        h.color.name() if hasattr(h.color, "name") else str(h.color)
                    )
                    seen_horizons[h.name] = color_val

        legend_patches = [
            mpatches.Patch(color=c, label=n) for n, c in seen_horizons.items()
        ]

        # Añadir la línea del terreno a la leyenda (color amarillo)
        terrain_line = matplotlib.lines.Line2D(
            [0], [0], color="#FFD700", linewidth=2.5, label="Terreno (DEM)"
        )
        ax.legend(handles=[terrain_line] + legend_patches, loc="upper right")

        # Conectar eventos de navegación (zoom/pan) para actualizar el área visible
        self.canvas.draw()

        # Actualizar el área visible inicial
        try:
            x_min, x_max = ax.get_xlim()
            self._update_view_extent(x_min, x_max)
        except Exception:
            pass

    def closeEvent(self, event):
        """Al cerrar el dock, limpiar los marcadores espaciales."""
        self.clear_spatial_markers()
        super().closeEvent(event)
