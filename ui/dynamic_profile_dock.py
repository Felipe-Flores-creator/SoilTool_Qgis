# -*- coding: utf-8 -*-
"""
Panel de Perfil Topográfico con estratigrafía edafológica (Matplotlib).

- Trazado de la línea A–A' en el mapa; la línea y sus extremos quedan marcados.
- Horizontes de suelo con color, patrón del material y límites según su nitidez.
- Exageración de la profundidad del suelo (para que los horizontes se vean
  frente al relieve) y exageración vertical del gráfico.
- Rótulos de las unidades de suelo atravesadas, cuadro de estadísticas y,
  opcionalmente, gráfico de pendientes por clases.
- Lectura bajo el cursor (distancia, cota, unidad y horizonte) sincronizada con
  un marcador en el mapa; el zoom del gráfico sombrea el tramo en el mapa.
- Exportación a PNG / PDF / SVG a 300 ppp.
"""

import math

import numpy as np
from qgis.PyQt.QtCore import QSize, Qt, QTimer
from qgis.PyQt.QtGui import QColor, QImage
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)
from qgis.core import QgsApplication, QgsGeometry, QgsMapLayerProxyModel, QgsPointXY
from qgis.gui import QgsMapLayerComboBox, QgsRubberBand, QgsVertexMarker

import matplotlib.patches as mpatches
from matplotlib.figure import Figure
from matplotlib.patches import ConnectionPatch
from matplotlib.lines import Line2D
from matplotlib.transforms import blended_transform_factory, offset_copy

try:  # matplotlib >= 3.5: backend Qt genérico (Qt5 en QGIS 3, Qt6 en QGIS 4)
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qtagg import (
        NavigationToolbar2QT as NavigationToolbar,
    )
except ImportError:  # matplotlib antiguo (QGIS 3 viejos)
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qt5agg import (
        NavigationToolbar2QT as NavigationToolbar,
    )

from ..core.dynamic_profile_engine import DynamicProfileEngine
from ..core.profile_engine import ProfileGeometry
from ..core.soil_symbology import pattern_key, render_column_image

# Patrones de matplotlib equivalentes a la simbología del informe PDF
HATCHES = {
    "sand": "..",
    "clay": "---",
    "silt": "--",
    "loam": "-.",
    "clay_loam": "--..",
    "silty_clay": "---",
    "sandy_loam": "..-",
    "sandy_clay": "..--",
    "gravel": "oo",
    "rock": "x",
    "limestone": "|-",
    "schist": "\\\\",
    "organic": "++",
    "peat": "++",
    "coal": "xxx",
    "ash": "**",
    "gypsum": "xx",
    "salt": "+",
    "generic": "",
}

BOUNDARY_STYLE = {
    "abrupt": dict(linestyle="-", linewidth=1.1),
    "clear": dict(linestyle="-", linewidth=0.7),
    "gradual": dict(linestyle=(0, (4, 2)), linewidth=0.7),
    "diffuse": dict(linestyle=(0, (1, 1.5)), linewidth=0.8),
}
BOUNDARY_NAMES = {
    "abrupt": "Límite abrupto",
    "clear": "Límite claro",
    "gradual": "Límite gradual",
    "diffuse": "Límite difuso",
}

SLOPE_CLASSES = [  # (hasta %, color, etiqueta)
    (5, "#81c784", "0–5 %"),
    (15, "#fff176", "5–15 %"),
    (30, "#ffb74d", "15–30 %"),
    (1e9, "#e57373", "> 30 %"),
]

C_TERRAIN = "#3e2723"
C_SUBSTRATE = "#eceff1"


def _qimage_to_rgba(img):
    """QImage -> array numpy (h, w, 4) uint8 para imshow."""
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    size = img.sizeInBytes() if hasattr(img, "sizeInBytes") else img.byteCount()
    ptr.setsize(size)
    arr = np.frombuffer(ptr, np.uint8).reshape(h, img.bytesPerLine())
    return arr[:, : w * 4].reshape(h, w, 4).copy()


def _draped_depths(horizons, n):
    """Profundidades (cm) estilizadas de cada límite a lo largo de un tramo.

    Usa la misma geometría que el Lienzo 2D (ruido según el tipo de límite,
    plegamiento, falla, inclinación y formas editadas con el lápiz) a la escala
    de referencia del Lienzo (300 px de ancho, 3 px/cm). Devuelve
    len(horizons) + 1 arrays de n valores (superficie primero).
    """
    W, S = 300.0, 3.0
    bounds = ProfileGeometry.compute_boundaries(horizons, W, S)
    t = np.linspace(0.0, 1.0, max(n, 1))
    out = []
    for i, pts in enumerate(bounds):
        bx = np.array([p.x() for p in pts]) / W
        by = np.array([p.y() for p in pts]) / S
        if i == 0 and not horizons[0].top_offsets:
            by = np.zeros_like(by)  # la superficie es el terreno
        out.append(np.interp(t, bx, by))
    for i in range(1, len(out)):  # nunca por encima del límite anterior
        out[i] = np.maximum(out[i], out[i - 1] + 0.2)
    return out


def _nice_factor(x):
    for f in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
        if f >= x:
            return f
    return 1000


class DynamicProfileDock(QDockWidget):
    """Dock inferior con el perfil topográfico y la estratigrafía edafológica."""

    def __init__(self, parent=None, iface=None):
        super().__init__("SoilTool - Perfil Topográfico", parent)
        # objectName: permite a QGIS guardar y restaurar su posición y tamaño
        self.setObjectName("SoilToolProfileDock")
        self.iface = iface
        self.points_data = []
        self.line_geometry = None
        self.map_crs = None
        self.total_m = 0.0
        self.map_tool = None
        # Acoplable en cualquier borde: si se separa, puede volver a anexarse
        # abajo, arriba o a un costado
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.setMinimumHeight(170)

        # Marcadores en el mapa
        self.position_marker = None
        self.view_extent_band = None
        self.line_band = None
        self.end_markers = []

        # Artistas del cursor (lectura)
        self._ax = None
        self._ax_slope = None
        self._cursor_artists = []
        self._soil_exag = 1.0

        # Redibujar tras cambiar el tamaño del panel (columnas y márgenes en px)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(250)
        self._resize_timer.timeout.connect(self._replot_if_data)

        self.setup_ui()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_bar()
        if self.points_data:
            self._resize_timer.start()

    def _relayout_bar(self):
        """Una línea si hay espacio; dos (capas arriba, acciones abajo) si no."""
        if not hasattr(self, "_bar_box"):
            return
        one_line = (
            self._row_a_w.minimumSizeHint().width()
            + self._row_b_w.minimumSizeHint().width()
            + 160  # holgura para que los selectores de capa sigan legibles
        )
        narrow = self.width() < one_line
        if narrow != self._narrow:
            self._narrow = narrow
            self._bar_box.setDirection(
                QBoxLayout.Direction.TopToBottom
                if narrow
                else QBoxLayout.Direction.LeftToRight
            )

    def _replot_if_data(self):
        if self.points_data:
            self.plot_profile()

    # ------------------------------------------------------------------
    # Interfaz
    # ------------------------------------------------------------------
    def setup_ui(self):
        """Barra compacta de una fila + menú de opciones + gráfico.

        Se mantiene un ancho mínimo pequeño para que el panel se acople abajo,
        entre los paneles laterales de QGIS, sin empujar ni tapar nada.
        """
        self.main_widget = QWidget()
        lay = QVBoxLayout(self.main_widget)
        lay.setContentsMargins(4, 3, 4, 0)
        lay.setSpacing(2)

        # Fila A: capas · Fila B: acciones. En paneles anchos van en una sola
        # línea; en angostos (p. ej. acoplado a un costado) la fila B baja.
        row_a = QHBoxLayout()
        row_a.setContentsMargins(0, 0, 0, 0)
        row_a.setSpacing(4)
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(4)

        def combo_layers(filt, tip):
            c = QgsMapLayerComboBox()
            c.setFilters(filt)
            c.setToolTip(tip)
            c.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            c.setMinimumContentsLength(6)
            c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return c

        row_a.addWidget(QLabel("DEM"))
        self.dem_combo = combo_layers(
            QgsMapLayerProxyModel.RasterLayer, "Modelo digital de elevación"
        )
        row_a.addWidget(self.dem_combo, 2)
        row_a.addWidget(QLabel("Suelos"))
        self.soils_combo = combo_layers(
            QgsMapLayerProxyModel.PolygonLayer, "Capa de unidades de suelo"
        )
        row_a.addWidget(self.soils_combo, 2)

        self.draw_btn = QPushButton("✏ Trazar")
        self.draw_btn.setCheckable(True)
        self.draw_btn.setToolTip(
            "Trazar perfil en el mapa\n"
            "Clic izquierdo: añadir vértice · Doble clic o clic derecho: terminar"
        )
        self.draw_btn.setStyleSheet(
            "QPushButton { font-weight: bold; background-color: #5d4037; color: white;"
            " padding: 2px 8px; border-radius: 3px; }"
            "QPushButton:checked { background-color: #e65100; }"
        )
        self.draw_btn.clicked.connect(self.toggle_draw_tool)
        bar.addWidget(self.draw_btn)

        def tool_button(icon, fallback, tip, slot):
            b = QToolButton()
            ic = QgsApplication.getThemeIcon(icon)
            if ic.isNull():
                b.setText(fallback)
            else:
                b.setIcon(ic)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(slot)
            bar.addWidget(b)
            return b

        self.recalc_btn = tool_button(
            "/mActionRefresh.svg",
            "⟳",
            "Recalcular la misma línea (tras cambiar DEM, capa de suelos o paso)",
            self.recalculate,
        )
        self.clear_btn = tool_button(
            "/mActionDeleteSelected.svg", "✕", "Limpiar el perfil", self.clear_profile
        )
        self.export_btn = tool_button(
            "/mActionFileSaveAs.svg",
            "⤓",
            "Exportar el gráfico a PNG, PDF o SVG (300 ppp)",
            self.export_dialog,
        )

        # --- Menú de opciones (no ocupa ancho en el panel) ---
        self.options_btn = QToolButton()
        ic = QgsApplication.getThemeIcon("/mActionOptions.svg")
        if not ic.isNull():
            self.options_btn.setIcon(ic)
        self.options_btn.setText("Opciones")
        self.options_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.options_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.options_btn.setAutoRaise(True)
        self.options_btn.setToolTip("Paso de muestreo, exageraciones y capas visibles")
        menu = QMenu(self.options_btn)
        opts = QWidget()
        form = QFormLayout(opts)
        form.setContentsMargins(10, 8, 10, 8)
        form.setSpacing(5)

        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.5, 500.0)
        self.step_spin.setValue(5.0)
        self.step_spin.setDecimals(1)
        self.step_spin.setSuffix(" m")
        self.step_spin.setToolTip("Distancia entre muestras a lo largo de la línea")
        form.addRow("Paso de muestreo", self.step_spin)

        self.soil_exag_combo = QComboBox()
        self.soil_exag_combo.addItem("Auto", 0)
        for f in (1, 2, 5, 10, 20, 50, 100, 200):
            self.soil_exag_combo.addItem(f"×{f}", f)
        self.soil_exag_combo.setToolTip(
            "Multiplica la profundidad de los horizontes para que se vean frente "
            "al relieve. 'Auto' la ajusta a ~15 % del desnivel."
        )
        form.addRow("Exageración del suelo", self.soil_exag_combo)

        self.ve_combo = QComboBox()
        self.ve_combo.addItem("Ajustar al panel", 0)
        for f in (1, 2, 5, 10, 20):
            self.ve_combo.addItem(f"×{f}", f)
        form.addRow("Exageración vertical", self.ve_combo)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["Metros (m)", "Kilómetros (km)"])
        form.addRow("Distancia en", self.unit_combo)

        self.units_check = QCheckBox("Unidades de suelo rotuladas")
        self.patterns_check = QCheckBox("Patrones de material")
        self.slope_check = QCheckBox("Gráfico de pendiente")
        self.columns_check = QCheckBox("Columnas del perfil a escala real")
        self.columns_check.setToolTip(
            "Sobre cada cruce con una unidad de suelo, la columna del perfil "
            "edafológico con su profundidad real (regla en cm)"
        )
        for chk in (
            self.units_check,
            self.patterns_check,
            self.slope_check,
            self.columns_check,
        ):
            chk.setChecked(True)
            form.addRow(chk)

        act = QWidgetAction(menu)
        act.setDefaultWidget(opts)
        menu.addAction(act)
        self.options_btn.setMenu(menu)
        bar.addWidget(self.options_btn)

        self.status_label = QLabel("Elige un DEM y pulsa «Trazar».")
        self.status_label.setStyleSheet("color: #6d4c41;")
        # Ignored: el texto nunca obliga a ensanchar el panel
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        bar.addWidget(self.status_label, 3)

        self._row_a_w = QWidget()
        self._row_a_w.setLayout(row_a)
        self._row_b_w = QWidget()
        self._row_b_w.setLayout(bar)
        self._bar_box = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._bar_box.setContentsMargins(0, 0, 0, 0)
        self._bar_box.setSpacing(4)
        self._bar_box.addWidget(self._row_a_w, 4)
        self._bar_box.addWidget(self._row_b_w, 5)
        lay.addLayout(self._bar_box)
        self._narrow = False

        for combo in (self.soil_exag_combo, self.ve_combo, self.unit_combo):
            combo.currentIndexChanged.connect(self.plot_profile)
        for chk in (
            self.units_check,
            self.patterns_check,
            self.slope_check,
            self.columns_check,
        ):
            chk.toggled.connect(self.plot_profile)

        # Gráfico
        self.figure = Figure(facecolor="white")
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.canvas.setMinimumSize(200, 110)
        lay.addWidget(self.canvas, 1)
        self.toolbar = NavigationToolbar(self.canvas, self.main_widget)
        self.toolbar.setIconSize(QSize(16, 16))
        self.toolbar.setMaximumHeight(28)
        lay.addWidget(self.toolbar)
        self.setWidget(self.main_widget)

        self.canvas.mpl_connect("motion_notify_event", self._on_plot_mouse_move)
        self.canvas.mpl_connect("axes_leave_event", self._on_plot_leave)
        self.canvas.mpl_connect("draw_event", self._on_plot_redraw)
        self._update_buttons()
        self._draw_placeholder()

    def _update_buttons(self):
        has = bool(self.points_data)
        self.recalc_btn.setEnabled(self.line_geometry is not None)
        self.clear_btn.setEnabled(has)
        self.export_btn.setEnabled(has)

    def _draw_placeholder(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.axis("off")
        ax.text(
            0.5,
            0.5,
            "Traza una línea en el mapa para generar el perfil topográfico\n"
            "Clic izquierdo: añadir vértice  ·  Doble clic / clic derecho: terminar",
            ha="center",
            va="center",
            color="#8d6e63",
            fontsize=9,
            transform=ax.transAxes,
        )
        self._ax = None
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Marcadores en el mapa
    # ------------------------------------------------------------------
    def _init_rubber_bands(self):
        if not self.iface:
            return
        canvas = self.iface.mapCanvas()
        if self.position_marker is None:
            m = QgsVertexMarker(canvas)
            m.setIconType(QgsVertexMarker.ICON_CIRCLE)
            m.setColor(QColor(230, 81, 0))
            m.setFillColor(QColor(255, 255, 255, 200))
            m.setIconSize(12)
            m.setPenWidth(3)
            m.hide()
            self.position_marker = m
        if self.view_extent_band is None:
            self.view_extent_band = QgsRubberBand(canvas)
            self.view_extent_band.setColor(QColor(0, 150, 255, 110))
            self.view_extent_band.setWidth(7)
        if self.line_band is None:
            self.line_band = QgsRubberBand(canvas)
            self.line_band.setColor(QColor(93, 64, 55, 230))
            self.line_band.setWidth(2)

    def _show_line_on_map(self):
        if not self.iface or not self.line_geometry:
            return
        self._init_rubber_bands()
        try:
            self.line_band.setToGeometry(self.line_geometry, None)
            self.line_band.show()
        except RuntimeError:
            self.line_band = None
        self._clear_end_markers()
        pts = self.line_geometry.asPolyline()
        if len(pts) >= 2:
            canvas = self.iface.mapCanvas()
            for pt, icon, color in (
                (pts[0], QgsVertexMarker.ICON_BOX, QColor(46, 125, 50)),
                (pts[-1], QgsVertexMarker.ICON_BOX, QColor(198, 40, 40)),
            ):
                m = QgsVertexMarker(canvas)
                m.setCenter(QgsPointXY(pt))
                m.setIconType(icon)
                m.setColor(color)
                m.setFillColor(color)
                m.setIconSize(10)
                m.setPenWidth(2)
                self.end_markers.append(m)

    def _clear_end_markers(self):
        if self.iface:
            scene = self.iface.mapCanvas().scene()
            for m in self.end_markers:
                try:
                    scene.removeItem(m)
                except RuntimeError:
                    pass
        self.end_markers = []

    def clear_spatial_markers(self):
        """Limpia marcadores de posición y tramo visible (no la línea)."""
        if self.position_marker:
            try:
                self.position_marker.hide()
            except RuntimeError:
                self.position_marker = None
        if self.view_extent_band:
            try:
                self.view_extent_band.reset()
            except RuntimeError:
                self.view_extent_band = None

    def _clear_all_map_items(self):
        self.clear_spatial_markers()
        if self.line_band:
            try:
                self.line_band.reset()
            except RuntimeError:
                self.line_band = None
        self._clear_end_markers()

    # ------------------------------------------------------------------
    # Trazado
    # ------------------------------------------------------------------
    def toggle_draw_tool(self, checked):
        if not self.iface:
            return
        if checked:
            from ..core.profile_map_tool import ProfileMapTool

            dem_layer = self.dem_combo.currentLayer()
            if dem_layer is None:
                QMessageBox.information(
                    self, "Perfil topográfico", "Selecciona primero una capa DEM."
                )
                self.draw_btn.setChecked(False)
                return
            self.map_tool = ProfileMapTool(self.iface.mapCanvas(), dem_layer)
            soils_layer = self.soils_combo.currentLayer()
            if soils_layer:
                self.map_tool.add_vector_layer(soils_layer)
            self.map_tool.profileComplete.connect(self.on_profile_drawn)
            self.iface.mapCanvas().setMapTool(self.map_tool)
            self.status_label.setText(
                "Clic: añadir vértice · Doble clic / clic derecho: terminar"
            )
        else:
            self.deactivate_tool()

    def deactivate_tool(self):
        if self.iface and self.map_tool is not None:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() == self.map_tool:
                canvas.unsetMapTool(self.map_tool)
                self.map_tool.cancel_drawing()
        self.draw_btn.blockSignals(True)
        self.draw_btn.setChecked(False)
        self.draw_btn.blockSignals(False)

    def on_profile_drawn(self, dem_profile_data):
        self.deactivate_tool()
        if not dem_profile_data or not dem_profile_data.polyline:
            return
        self.line_geometry = QgsGeometry.fromPolylineXY(dem_profile_data.polyline)
        self.map_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self.recalculate()

    def recalculate(self):
        """Muestrea de nuevo la línea actual con las capas y el paso actuales."""
        if not self.line_geometry:
            return
        if self.map_crs is None and self.iface:
            self.map_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self.points_data = DynamicProfileEngine.generate_dynamic_profile(
            dem_layer=self.dem_combo.currentLayer(),
            soils_layer=self.soils_combo.currentLayer(),
            line_geometry=self.line_geometry,
            step_size=self.step_spin.value(),
            map_crs=self.map_crs,
        )
        self.total_m = self.points_data[-1]["distance"] if self.points_data else 0.0
        self.clear_spatial_markers()
        self._show_line_on_map()
        self.plot_profile()

    def clear_profile(self):
        self.points_data = []
        self.line_geometry = None
        self.total_m = 0.0
        self._clear_all_map_items()
        self.status_label.setText("Elige un DEM y pulsa «Trazar».")
        self._draw_placeholder()
        self._update_buttons()

    # ------------------------------------------------------------------
    # Sincronización gráfico <-> mapa
    # ------------------------------------------------------------------
    def _point_at_distance(self, distance_m):
        if not self.line_geometry or self.total_m <= 0:
            return None
        frac = min(max(distance_m / self.total_m, 0.0), 1.0)
        g = self.line_geometry.interpolate(frac * self.line_geometry.length())
        return g.asPoint() if g and not g.isEmpty() else None

    def _interpolate_point_on_line(self, distance):
        """Compatibilidad: punto del mapa a 'distance' metros del inicio."""
        return self._point_at_distance(distance)

    def _update_position_marker(self, distance_m):
        if not self.iface:
            return
        self._init_rubber_bands()
        pt = self._point_at_distance(distance_m)
        if pt is None or self.position_marker is None:
            return
        try:
            self.position_marker.setCenter(QgsPointXY(pt))
            self.position_marker.show()
        except RuntimeError:
            self.position_marker = None

    def _update_view_extent(self, d_min, d_max):
        """Sombrea en el mapa el tramo visible del gráfico (en metros)."""
        if not self.iface or not self.line_geometry or not self.points_data:
            return
        self._init_rubber_bands()
        if self.view_extent_band is None:
            return
        try:
            self.view_extent_band.reset()
        except RuntimeError:
            self.view_extent_band = None
            return
        d_min, d_max = max(d_min, 0.0), min(d_max, self.total_m)
        if d_max - d_min >= self.total_m * 0.999:
            return  # se ve todo: no sombrear
        pts = [self._point_at_distance(d_min)]
        pts += [
            QgsPointXY(p["x"], p["y"])
            for p in self.points_data
            if d_min < p["distance"] < d_max
        ]
        pts.append(self._point_at_distance(d_max))
        pts = [p for p in pts if p is not None]
        if len(pts) >= 2:
            try:
                for p in pts:
                    self.view_extent_band.addPoint(QgsPointXY(p))
                self.view_extent_band.show()
            except RuntimeError:
                pass

    def _dist_scale(self):
        """Divisor para pasar metros a la unidad del eje X."""
        return 1000.0 if self.unit_combo.currentIndex() == 1 else 1.0

    def _get_scale_factor(self):
        """Compatibilidad: factor unidad-eje por metro."""
        return 1.0 / self._dist_scale()

    def _on_plot_mouse_move(self, event):
        if not self.points_data or self._ax is None:
            return
        if event.inaxes not in (self._ax, self._ax_slope) or event.xdata is None:
            return
        d_m = event.xdata * self._dist_scale()
        self._update_position_marker(d_m)
        self._update_cursor(d_m)

    def _on_plot_leave(self, event):
        for a in self._cursor_artists:
            a.set_visible(False)
        if self.position_marker:
            try:
                self.position_marker.hide()
            except RuntimeError:
                self.position_marker = None
        self.canvas.draw_idle()

    def _on_plot_redraw(self, event):
        if not self.points_data or self._ax is None:
            return
        try:
            x0, x1 = self._ax.get_xlim()
            s = self._dist_scale()
            self._update_view_extent(x0 * s, x1 * s)
        except Exception:
            pass

    def on_unit_changed(self, index):
        self.plot_profile()

    # ------------------------------------------------------------------
    # Dibujo
    # ------------------------------------------------------------------
    def _arrays(self):
        d = np.array([p["distance"] for p in self.points_data], dtype=float)
        z = np.array([p["z"] for p in self.points_data], dtype=float)
        return d, z

    def _runs(self):
        """Tramos consecutivos dentro de la misma entidad de suelo con horizontes."""
        runs, start = [], 0
        pts = self.points_data
        for i in range(1, len(pts) + 1):
            if i == len(pts) or pts[i]["fid"] != pts[start]["fid"]:
                if pts[start]["fid"] is not None:
                    runs.append((start, i - 1))
                start = i
        return runs

    def _soil_exaggeration(self, relief, max_depth_m):
        val = self.soil_exag_combo.currentData()
        if val:
            return float(val)
        if max_depth_m <= 0:
            return 1.0
        target = max(relief, 1.0) * 0.15
        return float(_nice_factor(max(1.0, target / max_depth_m)))

    def plot_profile(self, *args):
        self.figure.clear()
        self._cursor_artists = []
        self._ax = self._ax_slope = None
        self._update_buttons()
        if not self.points_data:
            self._draw_placeholder()
            return

        d, z = self._arrays()
        valid = np.isfinite(z)
        if not valid.any():
            self._draw_placeholder()
            self.status_label.setText("El DEM no tiene datos a lo largo de la línea.")
            return

        s = self._dist_scale()
        unit = "km" if s > 1 else "m"
        x = d / s
        zmin, zmax = float(np.nanmin(z)), float(np.nanmax(z))
        relief = zmax - zmin

        runs = self._runs()
        max_depth_m = 0.0
        for a, b in runs:
            hs = self.points_data[a]["horizons"]
            if hs:
                max_depth_m = max(max_depth_m, max(h.bottom for h in hs) / 100.0)
        exag = self._soil_exaggeration(relief, max_depth_m)
        self._soil_exag = exag

        # En paneles bajos se priorizan el perfil y luego las columnas
        fig_w_avail, fig_h_avail = self.figure.get_size_inches() * self.figure.dpi
        show_slope = self.slope_check.isChecked() and fig_h_avail >= 300
        soil_runs = [r for r in runs if self.points_data[r[0]]["horizons"]]
        show_cols = (
            self.columns_check.isChecked() and bool(soil_runs) and fig_h_avail >= 220
        )
        # Altura de la franja de columnas: al menos ~125 px si el panel es bajo
        fig_h_px = self.figure.get_size_inches()[1] * self.figure.dpi
        usable = max(fig_h_px - 100.0, 150.0)
        others = 4.0 + (1.0 if show_slope else 0.0)
        strip = min(4.0, max(2.0, others * 125.0 / max(usable - 125.0, 1.0)))
        ratios = ([strip] if show_cols else []) + [4] + ([1] if show_slope else [])
        gs = self.figure.add_gridspec(len(ratios), 1, height_ratios=ratios, hspace=0.10)
        row = 1 if show_cols else 0
        ax = self.figure.add_subplot(gs[row])
        ax_c = self.figure.add_subplot(gs[0], sharex=ax) if show_cols else None
        ax_s = self.figure.add_subplot(gs[row + 1], sharex=ax) if show_slope else None
        self._ax, self._ax_slope = ax, ax_s

        # Entradas de leyenda aproximadas para reservar el margen derecho
        leg_keys = {
            (h.name, h.color.name(), h.texture)
            for a, _ in soil_runs
            for h in self.points_data[a]["horizons"]
        }
        leg_bounds = {
            h.boundary_type
            for a, _ in soil_runs
            for h in self.points_data[a]["horizons"]
        }
        # Diseño adaptable al tamaño del panel
        show_legend = fig_w_avail >= 900
        many = 2 + len(leg_keys) + len(leg_bounds) > 14
        ncol = 2 if (many and fig_w_avail >= 1150) else 1
        if show_legend:
            right = 0.80 if ncol == 1 else 0.68
        else:
            right = 1.0 - 14.0 / max(fig_w_avail, 1.0)
        compact = fig_h_avail < 300
        # Márgenes en puntos tipográficos (independientes de la altura del dock)
        fig_h_pt = max(self.figure.get_size_inches()[1] * 72.0, 120.0)
        self.figure.subplots_adjust(
            left=min(0.2, 58.0 / max(fig_w_avail, 1.0)),
            right=right,
            top=1.0 - (24.0 if compact else 46.0) / fig_h_pt,
            bottom=30.0 / fig_h_pt,
        )

        base_y = zmin - max(relief * 0.12, max_depth_m * exag * 1.3, 1.0)
        top_y = zmax + max(relief * (0.22 if self.units_check.isChecked() else 0.08), 1)

        # Sustrato (bajo el terreno)
        ax.fill_between(
            x,
            np.where(valid, z, np.nan),
            base_y,
            color=C_SUBSTRATE,
            hatch="////" if self.patterns_check.isChecked() else None,
            edgecolor="#cfd8dc",
            linewidth=0,
            zorder=1,
        )

        legend_h = {}
        bound_used = set()
        for a, b in runs:
            hs = self.points_data[a]["horizons"]
            if not hs:
                continue
            end = b + 1
            xs = x[a:end]
            zs = z[a:end]
            depths = _draped_depths(hs, len(xs))
            for k, h in enumerate(hs):
                top = zs - depths[k] / 100.0 * exag
                bot = zs - depths[k + 1] / 100.0 * exag
                key, _ = pattern_key(h.texture)
                hatch = (
                    HATCHES.get(key, "") if self.patterns_check.isChecked() else None
                )
                ax.fill_between(
                    xs,
                    top,
                    bot,
                    facecolor=h.color.name(),
                    edgecolor=(0, 0, 0, 0.35),
                    hatch=hatch or None,
                    linewidth=0,
                    zorder=2,
                )
                style = BOUNDARY_STYLE.get(h.boundary_type, BOUNDARY_STYLE["clear"])
                ax.plot(xs, bot, color="#212121", alpha=0.75, zorder=3, **style)
                bound_used.add(h.boundary_type)
                lk = (h.name, h.color.name(), h.texture)
                if lk not in legend_h:
                    legend_h[lk] = mpatches.Patch(
                        facecolor=h.color.name(),
                        edgecolor=(0, 0, 0, 0.45),
                        hatch=hatch or None,
                        label=f"{h.name} – {h.texture}",
                    )

        # Terreno
        ax.plot(x, z, color=C_TERRAIN, linewidth=1.6, zorder=4, label="Terreno (DEM)")

        # Unidades de suelo: separadores y rótulos
        if self.units_check.isChecked():
            trans = blended_transform_factory(ax.transData, ax.transAxes)
            for a, b in runs:
                label = self.points_data[a]["unit"] or "s/ perfil"
                x0, x1 = x[a], x[b]
                for xv in (x0, x1):
                    ax.axvline(
                        xv, color="#8d6e63", linewidth=0.6, linestyle=":", zorder=1.5
                    )
                ax.plot(
                    [x0, x1],
                    [0.955, 0.955],
                    color="#8d6e63",
                    linewidth=1.0,
                    transform=trans,
                    zorder=5,
                    clip_on=False,
                )
                if not show_cols and (x1 - x0) > (x[-1] - x[0]) * 0.04:
                    ax.text(
                        (x0 + x1) / 2,
                        0.97,
                        label,
                        transform=trans,
                        ha="center",
                        va="bottom",
                        fontsize=7.5,
                        fontweight="bold",
                        color="#4e342e",
                        zorder=6,
                    )

        # Extremos A – A'
        for xv, txt, ha in ((x[0], "A", "left"), (x[-1], "A'", "right")):
            ax.annotate(
                txt,
                xy=(xv, 1.0),
                xycoords=("data", "axes fraction"),
                xytext=(3 if ha == "left" else -3, 3),
                textcoords="offset points",
                ha=ha,
                va="bottom",
                fontsize=10,
                fontweight="bold",
                color="#4e342e",
                annotation_clip=False,
            )

        ax.set_xlim(x[0], x[-1])
        ax.set_ylim(base_y, top_y)
        ax.set_ylabel("Cota (m s.n.m.)", fontsize=8)
        ax.tick_params(labelsize=7.5)
        ax.grid(True, color="#e0e0e0", linewidth=0.6, zorder=0)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)

        # Exageración vertical
        ve_fixed = self.ve_combo.currentData()
        if ve_fixed:
            ax.set_aspect(ve_fixed / s, adjustable="datalim")

        # Estadísticas
        stats = self._stats(d, z)
        info = (
            f"Longitud {self._fmt_len(self.total_m)}   ·   Cota {zmin:,.1f} – "
            f"{zmax:,.1f} m   ·   Desnivel {relief:,.1f} m\n"
            f"Pendiente media {stats['mean']:.1f} %   ·   máx. {stats['max']:.1f} %"
            f"   ·   Ascenso {stats['up']:,.0f} m / Descenso {stats['down']:,.0f} m"
        ).replace(",", " ")
        exag_txt = f"Profundidad del suelo exagerada ×{exag:g}"
        # Encabezado fijo arriba de la figura (título + estadísticas)
        fig = self.figure
        x_left = self.figure.subplotpars.left
        head = offset_copy(fig.transFigure, fig=fig, y=-5, units="points")
        if compact:
            length_txt = self._fmt_len(self.total_m)
            if fig_w_avail >= 620:
                short = (
                    f"Perfil topográfico  ·  {length_txt}  ·  "
                    f"desnivel {relief:.1f} m  ·  pend. media {stats['mean']:.1f} %"
                )
            elif fig_w_avail >= 420:
                short = f"Perfil  ·  {length_txt}  ·  desnivel {relief:.1f} m"
            else:
                short = f"{length_txt}  ·  Δ {relief:.1f} m"
            fig.text(
                x_left,
                1.0,
                short,
                transform=head,
                fontsize=8,
                fontweight="bold",
                color="#3e2723",
                va="top",
            )
        else:
            fig.text(
                x_left,
                1.0,
                "Perfil topográfico y estratigrafía edafológica",
                transform=head,
                fontsize=10,
                fontweight="bold",
                color="#3e2723",
                va="top",
            )
            sub = offset_copy(fig.transFigure, fig=fig, y=-19, units="points")
            fig.text(
                x_left, 1.0, info, transform=sub, fontsize=7, color="#5d4037", va="top"
            )
        if show_cols and not compact and fig_w_avail >= 700:
            fig.text(
                right,
                1.0,
                "Perfiles edafológicos intersectados\nprofundidad real (cm)",
                transform=sub,
                fontsize=7,
                style="italic",
                color="#6d4c41",
                ha="right",
                va="top",
            )
        if show_cols:
            self._draw_columns(ax_c, ax, x, z, soil_runs)
        ax.text(
            0.995,
            0.02,
            exag_txt,
            transform=ax.transAxes,
            fontsize=7,
            color="#6d4c41",
            ha="right",
            va="bottom",
            style="italic",
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#d7ccc8", alpha=0.9),
            zorder=7,
        )

        # Pendiente
        if ax_s is not None:
            self._plot_slope(ax_s, x, stats["slope"])
            ax_s.set_xlabel(f"Distancia ({unit})", fontsize=8)
            ax.tick_params(labelbottom=False)
        else:
            ax.set_xlabel(f"Distancia ({unit})", fontsize=8)

        # Leyenda (fuera del gráfico, a la derecha)
        handles = [Line2D([0], [0], color=C_TERRAIN, lw=1.6, label="Terreno (DEM)")]
        handles += list(legend_h.values())
        for bt in ("abrupt", "clear", "gradual", "diffuse"):
            if bt in bound_used:
                handles.append(
                    Line2D(
                        [0],
                        [0],
                        color="#212121",
                        label=BOUNDARY_NAMES[bt],
                        **BOUNDARY_STYLE[bt],
                    )
                )
        handles.append(
            mpatches.Patch(
                facecolor=C_SUBSTRATE,
                edgecolor="#cfd8dc",
                hatch="////" if self.patterns_check.isChecked() else None,
                label="Sustrato no descrito",
            )
        )
        if show_legend:
            ax.legend(
                handles=handles,
                loc="upper left",
                bbox_to_anchor=(1.01, 1.0),
                fontsize=7,
                frameon=False,
                ncol=ncol,
                handlelength=2.2,
                borderaxespad=0,
            )

        # Artistas del cursor
        vl = ax.axvline(x[0], color="#e65100", linewidth=0.9, zorder=8, visible=False)
        (dot,) = ax.plot(
            [x[0]],
            [z[0]],
            "o",
            ms=5,
            mfc="white",
            mec="#e65100",
            mew=1.5,
            zorder=9,
            visible=False,
        )
        box = ax.annotate(
            "",
            xy=(x[0], z[0]),
            xytext=(10, -10),
            textcoords="offset points",
            fontsize=7.2,
            va="top",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#8d6e63", alpha=0.95),
            zorder=10,
            visible=False,
        )
        box.set_clip_on(False)
        ax.set_zorder(3)  # el cuadro de lectura queda sobre el gráfico de pendiente
        self._cursor_artists = [vl, dot, box]
        if ax_s is not None:
            vl2 = ax_s.axvline(x[0], color="#e65100", linewidth=0.9, visible=False)
            self._cursor_artists.append(vl2)

        n_units = len(runs)
        self.status_label.setText(
            f"{len(self.points_data)} muestras · {n_units} tramo(s) con suelo"
        )
        self.figure.align_ylabels([a for a in (ax, ax_s) if a is not None])
        self.canvas.draw()

    def _draw_columns(self, ax_c, ax, x, z, soil_runs):
        """Columna del perfil a escala real sobre cada cruce con una unidad."""
        ax_c.set_ylim(0, 1)
        ax_c.axis("off")
        fig_w, fig_h = self.figure.get_size_inches() * self.figure.dpi
        pos = ax_c.get_position()
        strip_w_px = max(pos.width * fig_w, 1.0)
        strip_h_px = max(pos.height * fig_h, 1.0)
        col_h_frac = 0.80
        col_h_px = strip_h_px * col_h_frac
        col_w_px = max(64.0, min(col_h_px * 0.62, 140.0))
        x_range = (x[-1] - x[0]) or 1.0
        w_data = col_w_px / strip_w_px * x_range
        oversample = 2.0
        z_fill = np.where(np.isfinite(z), z, np.nanmin(z))
        last_right = -np.inf
        for a, b in soil_runs:
            hs = self.points_data[a]["horizons"]
            xc = (x[a] + x[b]) / 2.0
            if xc - w_data / 2 < last_right + w_data * 0.12:
                continue  # no cabe sin solaparse con la anterior
            last_right = xc + w_data / 2
            zc = float(np.interp(xc, x, z_fill))
            img = render_column_image(
                hs,
                col_w_px * oversample,
                col_h_px * oversample,
                unit=oversample * 0.9,
                shaped=True,
                labels=True,
                ruler=True,
                ruler_width=oversample * 23,
                font_px=oversample * 7.5,
            )
            ax_c.imshow(
                _qimage_to_rgba(img),
                extent=(xc - w_data / 2, xc + w_data / 2, 0.0, col_h_frac),
                aspect="auto",
                interpolation="antialiased",
                zorder=3,
            )
            depth = max(h.bottom for h in hs)
            unit = self.points_data[a]["unit"] or f"FID {self.points_data[a]['fid']}"
            ax_c.text(
                xc,
                col_h_frac + 0.03,
                f"{unit}  ·  {depth:g} cm",
                ha="center",
                va="bottom",
                fontsize=7.5,
                fontweight="bold",
                color="#4e342e",
                zorder=4,
            )
            con = ConnectionPatch(
                xyA=(xc, 0.0),
                coordsA=ax_c.transData,
                xyB=(xc, zc),
                coordsB=ax.transData,
                color="#8d6e63",
                linewidth=0.9,
                linestyle=(0, (3, 2)),
                zorder=6,
            )
            if hasattr(self.figure, "add_artist"):
                self.figure.add_artist(con)
            else:
                ax_c.add_artist(con)
            ax.plot(
                [xc],
                [zc],
                marker="v",
                ms=6,
                color="#8d6e63",
                mec="white",
                mew=0.8,
                zorder=7,
            )

    def _plot_slope(self, ax_s, x, slope):
        ax_s.fill_between(x, 0, slope, color="#bdbdbd", linewidth=0, step="mid")
        lo = 0
        for hi, color, label in SLOPE_CLASSES:
            mask = (np.abs(slope) >= lo) & (np.abs(slope) < hi)
            ax_s.fill_between(
                x,
                0,
                slope,
                where=mask,
                color=color,
                linewidth=0,
                step="mid",
                label=label,
            )
            lo = hi
        ax_s.axhline(0, color="#616161", linewidth=0.6)
        ax_s.set_ylabel("Pend. (%)", fontsize=8)
        ax_s.tick_params(labelsize=7)
        ax_s.grid(True, color="#eeeeee", linewidth=0.5)
        for sp in ("top", "right"):
            ax_s.spines[sp].set_visible(False)
        lim = max(5.0, float(np.nanmax(np.abs(slope))) * 1.15) if slope.size else 5
        ax_s.set_ylim(-lim, lim)
        # Leyenda de clases dentro del propio gráfico (no compite con la principal)
        ax_s.legend(
            loc="upper right",
            ncol=len(SLOPE_CLASSES),
            fontsize=6,
            frameon=True,
            framealpha=0.85,
            edgecolor="#e0e0e0",
            handlelength=1.2,
            columnspacing=0.8,
            borderpad=0.3,
        )

    @staticmethod
    def _stats(d, z):
        valid = np.isfinite(z)
        slope = np.full_like(z, np.nan)
        if valid.sum() >= 3:
            dv, zv = d[valid], z[valid]
            # Suavizado leve (ventana ~3 muestras) para no amplificar ruido del DEM
            k = 3
            zs = np.convolve(zv, np.ones(k) / k, mode="same")
            zs[0], zs[-1] = zv[0], zv[-1]
            g = np.gradient(zs, dv) * 100.0
            slope[valid] = g
        dz = np.diff(z[valid]) if valid.sum() > 1 else np.array([0.0])
        abs_s = np.abs(slope[np.isfinite(slope)])
        return {
            "slope": np.nan_to_num(slope),
            "mean": float(abs_s.mean()) if abs_s.size else 0.0,
            "max": float(abs_s.max()) if abs_s.size else 0.0,
            "up": float(dz[dz > 0].sum()),
            "down": float(-dz[dz < 0].sum()),
        }

    @staticmethod
    def _fmt_len(m):
        return f"{m / 1000:.2f} km" if m >= 1000 else f"{m:.0f} m"

    def _update_cursor(self, d_m):
        if not self._cursor_artists:
            return
        d, z = self._arrays()
        i = int(np.clip(np.searchsorted(d, d_m), 0, len(d) - 1))
        if i > 0 and abs(d[i - 1] - d_m) < abs(d[i] - d_m):
            i -= 1
        p = self.points_data[i]
        xv = d[i] / self._dist_scale()
        zv = z[i]
        vl, dot, box = self._cursor_artists[:3]
        vl.set_xdata([xv, xv])
        if math.isfinite(zv):
            dot.set_data([xv], [zv])
            dot.set_visible(True)
        else:
            dot.set_visible(False)
        lines = [
            f"Distancia: {self._fmt_len(d[i])}",
            f"Cota: {zv:.1f} m" if math.isfinite(zv) else "Cota: sin dato",
        ]
        if p["fid"] is not None:
            lines.append(f"Unidad: {p['unit'] or 'FID ' + str(p['fid'])}")
            for h in p["horizons"]:
                lines.append(f"  {h.name}: {h.top:g}–{h.bottom:g} cm · {h.texture}")
        else:
            lines.append("Sin unidad de suelo")
        box.set_text("\n".join(lines[:12]))
        y_anchor = zv if math.isfinite(zv) else sum(self._ax.get_ylim()) / 2
        box.xy = (xv, y_anchor)
        # Abrir el cuadro hacia el lado con más espacio
        x0, x1 = self._ax.get_xlim()
        right_side = (xv - x0) < (x1 - x0) * 0.6
        y0, y1 = self._ax.get_ylim()
        upper = (y_anchor - y0) > (y1 - y0) * 0.5
        box.set_position((10 if right_side else -10, -10 if upper else 10))
        box.set_ha("left" if right_side else "right")
        box.set_va("top" if upper else "bottom")
        for a in self._cursor_artists:
            if a is not dot:
                a.set_visible(True)
        if len(self._cursor_artists) > 3:
            self._cursor_artists[3].set_xdata([xv, xv])
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Exportación
    # ------------------------------------------------------------------
    def export_dialog(self):
        if not self.points_data:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar perfil topográfico",
            "perfil_topografico.png",
            "Imagen PNG (*.png);;Documento PDF (*.pdf);;Vectorial SVG (*.svg)",
        )
        if not path:
            return
        ok, msg = self.export_figure(path)
        if ok:
            QMessageBox.information(self, "Perfil exportado", msg)
        else:
            QMessageBox.critical(self, "Error al exportar", msg)

    def export_figure(self, path, dpi=300, size_in=(13.0, 6.5)):
        """Guarda el gráfico en alta resolución con el diseño completo
        (leyenda, columnas y pendiente), sea cual sea el tamaño del panel."""
        original = self.figure.get_size_inches().copy()
        try:
            self.figure.set_size_inches(*size_in, forward=False)
            self.plot_profile()
            for a in self._cursor_artists:
                a.set_visible(False)
            self.figure.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
            return True, f"Perfil guardado en:\n{path}"
        except Exception as e:
            return False, str(e)
        finally:
            self.figure.set_size_inches(*original, forward=False)
            self.plot_profile()

    def closeEvent(self, event):
        """Al cerrar el dock, limpiar los marcadores del mapa."""
        self._clear_all_map_items()
        super().closeEvent(event)
