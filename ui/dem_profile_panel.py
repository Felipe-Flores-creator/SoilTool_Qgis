# -*- coding: utf-8 -*-
"""
Panel horizontal para visualizar perfiles topográficos extraídos del DEM.
Muestra el perfil de elevación con los horizontes de suelo posicionados
bajo la superficie del terreno, con visualización profesional integrada.
"""

import math

from qgis.PyQt.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QFrame,
    QSizePolicy,
    QMessageBox,
    QFileDialog,
    QCheckBox,
)
from qgis.PyQt.QtGui import (
    QPainter,
    QPen,
    QBrush,
    QColor,
    QPainterPath,
    QLinearGradient,
    QFont,
    QPixmap,
    QFontMetrics,
)
from qgis.PyQt.QtCore import Qt, QRectF, pyqtSignal, QSize, QPointF

from ..core.materials import get_material_names
from ..core.horizon_manager import HorizonManager


class DEMProfileCanvas(QWidget):
    edit_changed = pyqtSignal()

    """Canvas personalizado para dibujar el perfil DEM con horizontes.
    Muestra la línea de superficie del DEM, los horizontes de suelo
    como rellenos estratigráficos bajo la superficie, con escala de
    profundidad y etiquetado profesional.

    Prototipo de edición en pantalla:
    - Arrastre vertical del vértice más cercano del horizonte (top/bottom).
    - Solo activa cuando edit_enabled=True (checkbox del panel).
    """

    # --- Soporte: horizontes/celdas manuales por tramo (start_d/end_d) ---
    # Implementación:
    # - manual_segments: lista de segmentos manuales sobre el perfil.
    # - Cada segmento tiene su propio HorizonData (top/bottom en cm) + extensión (start_d/end_d).
    # - Render: se dibujan como un horizonte adicional dentro del tramo.
    # - Edición: si edit_enabled=True, los top/bottom de manuales también son arrastrables.
    # - Persistencia: la conversión a HorizonData global (perfil edafológico) se hace desde DEMProfilePanel.

    # Estr. segmento (internal):
    # {
    #   "start_d": float, "end_d": float,
    #   "horizon": HorizonData (top/bottom cm, color/texture/name/etc),
    #   "h_idx": int (índice interno para tracks/edición)
    # }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile_data = None
        self.setMinimumSize(400, 250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Configuración de dibujo
        self.margin_left = 65
        self.margin_right = 25
        self.margin_top = 35
        self.margin_bottom = 50
        self.padding = 5

        # Unidad de visualización: 'm' para metros, 'cm' para centímetros
        self.display_unit = "m"
        self.display_scale = 1.0  # 1.0 para metros, 100.0 para centímetros

        # Colores
        self.bg_color = QColor(255, 255, 255)
        self.grid_color = QColor(220, 220, 220, 120)
        self.line_color = QColor(80, 80, 80)
        self.fill_color = QColor(180, 210, 180, 60)
        self.text_color = QColor(50, 50, 50)
        self.surface_color = QColor(
            255, 200, 0
        )  # Amarillo fuerte para línea de superficie
        self.surface_fill = QColor(255, 200, 0, 30)

        # Colores para horizonte de profundidad
        self.depth_scale_color = QColor(60, 60, 60, 100)
        self.horizon_border_color = QColor(80, 80, 80, 50)

        # Cache para evitar recálculos
        self._cached_pixmap = None
        self._needs_redraw = True
        self._cache_width = -1
        self._cache_height = -1

        # Bandera para evitar recursión de paint events
        self._in_paint_event = False

        # --- Edición en pantalla (prototipo) ---
        self.edit_enabled = False

        # Manual segments + estado de captura de tramo
        self.manual_segments = []  # lista de dicts (ver top del archivo)
        self._manual_add_mode = False
        self._manual_add_first_click_d = None  # start_d
        self._manual_pending_horizon_data = None  # HorizonData hasta definir tramo
        self.cells = []

        # tracks: lista de dicts:
        # { 'source' in ('detected','manual'), 'ifeat_idx' or 'mseg_idx', 'h_idx', 'kind' ('top','bottom'), 'points': [ {'d','e'}, ... ] }
        self._edit_tracks = []
        self._edit_tracks_ready = False

        self._dragging = False
        self._drag_target = None  # (track_idx, point_idx)
        self._drag_start_screen_y = 0
        self._drag_start_e = 0.0

        self._edit_snap_distance_tolerance_px = 6  # umbral en pixeles
        self._edit_hover_target = None

        # Coordenadas de última renderización (para convertir y↔elevación)
        self._last_draw_params = None  # dict

    def set_cells(self, cells):
        self.cells = cells
        self.update()

    def set_edit_enabled(self, enabled: bool):
        self.edit_enabled = bool(enabled)
        self._edit_tracks_ready = False
        self._edit_tracks = []
        self._dragging = False
        self._drag_target = None
        self.update()

    def clear_edit_state(self):
        self._edit_tracks = []
        self._edit_tracks_ready = False
        self._dragging = False
        self._drag_target = None
        self._last_draw_params = None

    def clear_manual_segments(self):
        self.manual_segments = []
        self._manual_add_mode = False
        self._manual_add_first_click_d = None
        self._manual_pending_horizon_data = None
        self._edit_tracks_ready = False
        self._edit_tracks = []
        self.update()

    def start_manual_cell_add(self, horizon_data):
        """
        Entra en modo: siguiente clic define start_d, siguiente clic define end_d.
        horizon_data: HorizonData con top/bottom cm + simbología (color/texture/name/etc)
        """
        if not self.profile_data or not getattr(self.profile_data, "points", None):
            return False
        if not horizon_data:
            return False

        total_distance = float(getattr(self.profile_data, "total_distance", 0) or 0)
        if total_distance <= 0:
            return False

        self._manual_add_mode = True
        self._manual_add_first_click_d = None
        self._manual_pending_horizon_data = horizon_data
        self._edit_tracks_ready = False
        self._edit_tracks = []
        self.update()
        return True

    def cancel_manual_cell_add(self):
        self._manual_add_mode = False
        self._manual_add_first_click_d = None
        self._manual_pending_horizon_data = None
        self._edit_tracks_ready = False
        self._edit_tracks = []
        self.update()

    def _build_edit_tracks(self, data):
        """
        Construye polilíneas editables (top/bottom) para:
        - horizontes detectados por intersección (intersected_features)
        - horizontes manuales por tramo (manual_segments)
        Se basa en el mismo cálculo que el render original:
        - segment_points: (pt_dist, h_top_elev, h_bottom_elev)
        Guardamos los vértices como (distance, elevation) para editar solo elevation.
        """
        self._edit_tracks = []
        if data is None:
            self._edit_tracks_ready = True
            return

        points = getattr(data, "points", None) or []
        if len(points) < 2:
            self._edit_tracks_ready = True
            return

        intersected_features = getattr(data, "intersected_features", None) or []

        # Recalcular parámetros de mapeo como en _draw_profile para convertir bien
        intersected_features_for_depth = intersected_features or []
        max_horizon_depth = 0
        for ifeat in intersected_features_for_depth:
            horizons = getattr(ifeat, "horizons", None) or []
            for h in horizons:
                try:
                    if h.bottom > max_horizon_depth:
                        max_horizon_depth = h.bottom
                except Exception:
                    continue

        max_depth_m = max_horizon_depth / 100.0

        try:
            elev_min = data.min_elevation
            elev_max = data.max_elevation
        except Exception:
            self._edit_tracks_ready = True
            return

        elev_range = elev_max - elev_min
        # Factor de amplificación vertical para que los horizontes se vean más grandes
        # Multiplicamos por 2.0 para duplicar la profundidad visible
        depth_amplify = 2.0
        if max_depth_m > 0:
            y_min_display = elev_min - max_depth_m * 1.3 * depth_amplify
        else:
            y_min_display = elev_min - elev_range * 0.1

        y_max_display = elev_max + elev_range * 0.15
        y_display_range = y_max_display - y_min_display
        if y_display_range <= 0:
            y_display_range = 1

        try:
            total_distance_val = float(getattr(data, "total_distance", 0) or 0)
        except Exception:
            total_distance_val = 0
        total_distance = total_distance_val if total_distance_val > 0 else 1

        # guardamos para conversión inversa al arrastrar
        self._last_draw_params = {
            "draw_left": self.margin_left,
            "draw_right": self.width() - self.margin_right,
            "draw_top": self.margin_top,
            "draw_bottom": self.height() - self.margin_bottom,
            "draw_width": (self.width() - self.margin_right) - self.margin_left,
            "draw_height": (self.height() - self.margin_bottom) - self.margin_top,
            "y_min_display": y_min_display,
            "y_display_range": y_display_range,
            "total_distance": total_distance,
        }

        # Helper: superficie interpolada sobre d (para manuales)
        def _interp_surface_elev_at(d):
            if d <= points[0].distance:
                return points[0].elevation
            if d >= points[-1].distance:
                return points[-1].elevation
            low, high = 0, len(points) - 1
            while high - low > 1:
                mid = (low + high) // 2
                if points[mid].distance <= d:
                    low = mid
                else:
                    high = mid
            p1 = points[low]
            p2 = points[high]
            if p2.distance - p1.distance < 1e-6:
                return p1.elevation
            ratio = (d - p1.distance) / (p2.distance - p1.distance)
            return p1.elevation + ratio * (p2.elevation - p1.elevation)

        # Crear tracks para horizontes detectados
        for ifeat_idx, ifeat in enumerate(intersected_features):
            horizons = getattr(ifeat, "horizons", None) or []
            if not horizons:
                continue

            start_d = getattr(ifeat, "intersection_start", 0.0)
            end_d = getattr(ifeat, "intersection_end", 0.0)
            elev_start = getattr(ifeat, "surface_elevation_start", None)
            elev_end = getattr(ifeat, "surface_elevation_end", None)

            if elev_start is None or elev_end is None:
                continue
            if end_d - start_d < 0.01:
                continue

            # puntos dentro del tramo para este feature
            for h_idx, h in enumerate(horizons):
                # h.top y h.bottom ya están en metros (elevación) según los almacena
                # _assign_horizons_to_points en dem_profile_engine.py.
                # No se debe dividir por 100, son elevaciones en metros directamente.
                segment_points = []
                for pt in points:
                    try:
                        pt_dist = pt.distance
                        if start_d <= pt_dist <= end_d:
                            h_top_elev = h.top
                            h_bottom_elev = h.bottom
                            segment_points.append((pt_dist, h_top_elev, h_bottom_elev))
                    except Exception:
                        continue

                if len(segment_points) < 2:
                    continue

                top_track = {
                    "ifeat_idx": ifeat_idx,
                    "h_idx": h_idx,
                    "kind": "top",
                    "points": [
                        {"d": d, "e": top_e} for (d, top_e, _) in segment_points
                    ],
                }
                bottom_track = {
                    "ifeat_idx": ifeat_idx,
                    "h_idx": h_idx,
                    "kind": "bottom",
                    "points": [
                        {"d": d, "e": bottom_e} for (d, _, bottom_e) in segment_points
                    ],
                }
                self._edit_tracks.append(top_track)
                self._edit_tracks.append(bottom_track)

        # Crear tracks para horizontes manuales
        for mseg_idx, mseg in enumerate(self.manual_segments or []):
            try:
                start_d = float(mseg.get("start_d"))
                end_d = float(mseg.get("end_d"))
                h = mseg.get("horizon")
            except Exception:
                continue

            if h is None:
                continue
            if end_d - start_d < 0.01:
                continue

            try:
                top_depth_m = -float(h.top) / 100.0
                bottom_depth_m = -float(h.bottom) / 100.0
            except Exception:
                continue

            segment_points = []
            for pt in points:
                pt_dist = float(pt.distance)
                if start_d <= pt_dist <= end_d:
                    surf_elev = _interp_surface_elev_at(pt_dist)
                    if surf_elev is None:
                        continue
                    h_top_elev = surf_elev + top_depth_m
                    h_bottom_elev = surf_elev + bottom_depth_m
                    segment_points.append((pt_dist, h_top_elev, h_bottom_elev))

            if len(segment_points) < 2:
                continue

            top_track = {
                "ifeat_idx": mseg_idx,  # para compat con _get_edit_points_by_key actual (siempre usa ifeat_idx)
                "h_idx": mseg_idx,  # clave (mseg_idx, mseg_idx, kind)
                "kind": "top",
                "points": [{"d": d, "e": top_e} for (d, top_e, _) in segment_points],
            }
            bottom_track = {
                "ifeat_idx": mseg_idx,
                "h_idx": mseg_idx,
                "kind": "bottom",
                "points": [
                    {"d": d, "e": bottom_e} for (d, _, bottom_e) in segment_points
                ],
            }

            self._edit_tracks.append(top_track)
            self._edit_tracks.append(bottom_track)

        self._edit_tracks_ready = True

    def set_profile_data(self, profile_data):
        """Establece los datos del perfil a dibujar."""
        self.profile_data = profile_data
        self._needs_redraw = True
        self._cached_pixmap = None
        self.update()

    def clear(self):
        """Limpia el perfil."""
        self.profile_data = None
        self._cached_pixmap = None
        self._needs_redraw = True
        self.update()

    def resizeEvent(self, event):
        """Forzar redibujo en resize."""
        self._needs_redraw = True
        super().resizeEvent(event)

    def save_image(self, file_path):
        """Guarda el perfil como imagen."""
        if not self.profile_data or not self.profile_data.points:
            return False

        # Usar tamaño mayor para exportación de alta calidad
        export_width = max(self.width(), 1200)
        export_height = max(self.height(), 600)
        pixmap = QPixmap(export_width, export_height)
        pixmap.fill(Qt.white)
        try:
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            self._draw_profile(painter, export_width, export_height)
        except Exception:
            return False

        return pixmap.save(file_path)

    def paintEvent(self, event):
        """Evento de pintado principal. Protegido contra recursión y cambios de estado."""
        if self._in_paint_event:
            return

        # Mitigación clave (QGIS/Qt5.15 en Windows): evitar repintados cuando el
        # widget está oculto o en transición de layout/dock.
        if not self.isVisible() or self.width() <= 0 or self.height() <= 0:
            return

        # Snapshot local para evitar que profile_data cambie durante el paint.
        data = self.profile_data
        points = None
        try:
            points = getattr(data, "points", None) if data is not None else None
        except Exception:
            points = None

        self._in_paint_event = True
        try:
            if data is None or not points:
                painter = QPainter(self)
                painter.fillRect(self.rect(), self.bg_color)
                painter.setPen(QColor(150, 150, 150))
                font = painter.font()
                font.setPointSize(11)
                painter.setFont(font)
                painter.drawText(
                    self.rect(),
                    Qt.AlignCenter,
                    "Dibuje una línea sobre el DEM\npara generar el perfil topográfico",
                )
                return

            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)

            if self.edit_enabled and not self._edit_tracks_ready:
                self._build_edit_tracks(data)

            # Pasar el snapshot al dibujado para no depender de self.profile_data.
            self._draw_profile(painter, self.width(), self.height(), data)
        finally:
            self._in_paint_event = False

    def _get_edit_points_by_key(self):
        """
        Convierte self._edit_tracks a un dict:
          (ifeat_idx, h_idx, kind) -> sorted list of (d, e)
        """
        out = {}
        for t in self._edit_tracks:
            key = (t.get("ifeat_idx"), t.get("h_idx"), t.get("kind"))
            pts = t.get("points") or []
            pts_sorted = sorted(pts, key=lambda x: x.get("d", 0.0))
            out[key] = [(p.get("d", 0.0), p.get("e", 0.0)) for p in pts_sorted]
        return out

    def _screen_y_to_elevation(self, screen_y: float):
        """Convierte coordenada Y de pantalla a elevación usando el último render."""
        if not self._last_draw_params:
            return None
        draw_bottom = self._last_draw_params["draw_bottom"]
        draw_top = self._last_draw_params["draw_top"]
        draw_height = self._last_draw_params["draw_height"]
        y_min_display = self._last_draw_params["y_min_display"]
        y_display_range = self._last_draw_params["y_display_range"]

        if draw_height <= 0 or y_display_range <= 0:
            return None

        # y = draw_bottom - ((elev - y_min_display)/y_display_range)*draw_height
        # => ((elev - y_min_display)/y_display_range) = (draw_bottom - y)/draw_height
        frac = (draw_bottom - screen_y) / draw_height
        elev = y_min_display + frac * y_display_range
        return elev

    def _find_nearest_vertex(self, mouse_x: float, mouse_y: float):
        """
        Encuentra el (track_idx, point_idx) más cercano.
        Criterio: distancia en pixeles al punto (x_proyectado, y_proyectado de elevación).
        """
        if (
            not self._edit_tracks_ready
            or not self._edit_tracks
            or not self._last_draw_params
        ):
            return None

        best = None
        best_dist2 = None

        draw_left = self._last_draw_params["draw_left"]
        draw_width = self._last_draw_params["draw_width"]
        total_distance = self._last_draw_params["total_distance"]

        # Convert screen x to distance is unnecessary: distancia por x se obtiene al proyectar d.
        # Proyectamos cada punto a pantalla: x(d), y(e)
        for ti, t in enumerate(self._edit_tracks):
            kind = t.get("kind")
            pts = t.get("points") or []
            for pi, p in enumerate(pts):
                d = p.get("d", 0.0)
                e = p.get("e", 0.0)

                x = draw_left + (d / total_distance) * draw_width
                # y usando elevación y_min_display/rango
                draw_bottom = self._last_draw_params["draw_bottom"]
                draw_top = self._last_draw_params["draw_top"]
                draw_height = self._last_draw_params["draw_height"]
                y_min_display = self._last_draw_params["y_min_display"]
                y_display_range = self._last_draw_params["y_display_range"]
                if draw_height <= 0 or y_display_range <= 0:
                    continue
                y = draw_bottom - ((e - y_min_display) / y_display_range) * draw_height

                dx = x - mouse_x
                dy = y - mouse_y
                dist2 = dx * dx + dy * dy
                if best_dist2 is None or dist2 < best_dist2:
                    best_dist2 = dist2
                    best = (ti, pi)

        if best is None:
            return None

        tol2 = float(self._edit_snap_distance_tolerance_px) ** 2
        if best_dist2 is not None and best_dist2 <= tol2:
            return best
        return None

    def mousePressEvent(self, event):
        # 1) Si estamos creando una celda manual: clics definen start_d/end_d
        if self._manual_add_mode and event.button() == Qt.LeftButton:
            if (
                not self._last_draw_params
                or not self.profile_data
                or not getattr(self.profile_data, "points", None)
            ):
                return

            # Convertir click a elevación con y, pero para d necesitamos la proyección en X
            x = float(event.pos().x())
            draw_left = self._last_draw_params["draw_left"]
            draw_width = self._last_draw_params["draw_width"]
            total_distance = float(self._last_draw_params["total_distance"] or 0)
            if draw_width <= 0 or total_distance <= 0:
                return

            # d = (x - draw_left)/draw_width * total_distance
            d_click = ((x - draw_left) / draw_width) * total_distance
            # clamp
            d_click = max(0.0, min(total_distance, d_click))

            if self._manual_add_first_click_d is None:
                self._manual_add_first_click_d = float(d_click)
                event.accept()
                self.update()
                return
            else:
                start_d = float(self._manual_add_first_click_d)
                end_d = float(d_click)
                if end_d < start_d:
                    start_d, end_d = end_d, start_d

                horizon_data = self._manual_pending_horizon_data
                if horizon_data is None:
                    self.cancel_manual_cell_add()
                    return

                # Crear segmento manual
                mseg_idx = len(self.manual_segments)
                self.manual_segments.append(
                    {
                        "start_d": start_d,
                        "end_d": end_d,
                        "horizon": horizon_data,
                        "h_idx": mseg_idx,
                    }
                )

                # Salir modo add y reconstruir tracks para permitir edición inmediata si edit_enabled=True
                self._manual_add_mode = False
                self._manual_add_first_click_d = None
                self._manual_pending_horizon_data = None
                self._edit_tracks_ready = False
                self._edit_tracks = []
                self.update()

                event.accept()
                return

        # 2) Edición (arrastre) de top/bottom
        if not self.edit_enabled:
            return
        if event.button() != Qt.LeftButton:
            return
        if not self._edit_tracks_ready or not self.profile_data:
            return

        target = self._find_nearest_vertex(
            float(event.pos().x()), float(event.pos().y())
        )
        if target is None:
            return

        self._dragging = True
        self._drag_target = target
        self._drag_start_screen_y = float(event.pos().y())
        ti, pi = target
        self._drag_start_e = float(self._edit_tracks[ti]["points"][pi]["e"])
        event.accept()

    def mouseMoveEvent(self, event):

        if not self.edit_enabled:
            return
        if not self.profile_data:
            return

        x = float(event.pos().x())
        y = float(event.pos().y())

        if self._dragging and self._drag_target:
            elev = self._screen_y_to_elevation(y)
            if elev is None:
                return

            ti, pi = self._drag_target
            # Actualizar elevación del vértice manteniendo distancia d
            self._edit_tracks[ti]["points"][pi]["e"] = float(elev)
            self._needs_redraw = True
            self.edit_changed.emit()
            self.update()
            event.accept()
            return

        # Hover (solo por feedback mínimo)
        self._edit_hover_target = self._find_nearest_vertex(x, y)
        if self._edit_hover_target is not None:
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if not self.edit_enabled:
            return
        if event.button() != Qt.LeftButton:
            return
        self._dragging = False
        self._drag_target = None
        self.update()
        self.setCursor(Qt.ArrowCursor)

    def _draw_profile(self, painter, width, height, data):
        """Dibuja el perfil completo: línea de superficie + horizontes con profundidad."""
        if data is None:
            return

        points = getattr(data, "points", None)
        if not points or len(points) < 2:
            return

        # --- Área de dibujo disponible ---
        draw_left = self.margin_left
        draw_right = width - self.margin_right
        draw_width = draw_right - draw_left
        draw_top = self.margin_top
        draw_bottom = height - self.margin_bottom
        draw_height = draw_bottom - draw_top

        if draw_width <= 0 or draw_height <= 0:
            return

        # --- Determinar la profundidad máxima a mostrar ---
        max_horizon_depth = 0
        min_horizon_thickness = float("inf")
        intersected_features = getattr(data, "intersected_features", None) or []
        for ifeat in intersected_features:
            horizons = getattr(ifeat, "horizons", None) or []
            for h in horizons:
                try:
                    if h.bottom > max_horizon_depth:
                        max_horizon_depth = h.bottom
                    thickness = h.bottom - h.top
                    if thickness > 0 and thickness < min_horizon_thickness:
                        min_horizon_thickness = thickness
                except Exception:
                    continue

        max_depth_m = max_horizon_depth / 100.0

        try:
            elev_min = data.min_elevation
            elev_max = data.max_elevation
        except Exception:
            # Si falta info crítica, abortar para evitar pintar con datos corruptos.
            return
        elev_range = elev_max - elev_min

        # Amplificación vertical adaptativa:
        # Si los horizontes son muy delgados (< 30 cm = 0.3m), amplificar mucho más
        # para que sean visibles. Si son gruesos, amplificación moderada.
        if min_horizon_thickness < float("inf") and min_horizon_thickness > 0:
            min_thick_m = min_horizon_thickness / 100.0
            # Escala: si el horizonte más delgado es 0.1m -> amplificar 6x; si es 1m -> 2x
            depth_amplify = max(2.0, min(8.0, 0.6 / min_thick_m))
        else:
            depth_amplify = 2.0

        # Si estamos en modo centímetros, aumentar amplificación para ver más detalle
        if self.display_unit == "cm":
            depth_amplify *= 1.5

        if max_depth_m > 0:
            y_min_display = elev_min - max_depth_m * 1.3 * depth_amplify
        else:
            y_min_display = elev_min - elev_range * 0.1

        y_max_display = elev_max + elev_range * 0.15
        y_display_range = y_max_display - y_min_display

        if y_display_range <= 0:
            y_display_range = 1

        try:
            total_distance_val = float(getattr(data, "total_distance", 0) or 0)
        except Exception:
            total_distance_val = 0
        total_distance = total_distance_val if total_distance_val > 0 else 1

        # Guardar params actuales para interacción
        self._last_draw_params = {
            "draw_left": draw_left,
            "draw_right": draw_right,
            "draw_top": draw_top,
            "draw_bottom": draw_bottom,
            "draw_width": draw_width,
            "draw_height": draw_height,
            "y_min_display": y_min_display,
            "y_display_range": y_display_range,
            "total_distance": total_distance,
        }

        def map_to_screen(distance, elevation):
            x = draw_left + (distance / total_distance) * draw_width
            y = (
                draw_bottom
                - ((elevation - y_min_display) / y_display_range) * draw_height
            )
            return x, y

        def map_dist_to_screen_x(distance):
            return draw_left + (distance / total_distance) * draw_width

        # ---- FONDO ----
        painter.fillRect(
            draw_left - self.padding,
            draw_top - self.padding,
            draw_width + 2 * self.padding,
            draw_height + 2 * self.padding,
            QColor(248, 248, 245),
        )

        # ---- CUADRÍCULA ----
        painter.setPen(QPen(self.grid_color, 0.5, Qt.DashLine))

        num_vert_lines = max(4, min(int(draw_width / 80), 20))
        for i in range(num_vert_lines + 1):
            x = draw_left + (i / num_vert_lines) * draw_width
            painter.drawLine(int(x), draw_top, int(x), draw_bottom)

        num_horiz_lines = max(3, min(int(draw_height / 50), 15))
        for i in range(num_horiz_lines + 1):
            y = draw_top + (i / num_horiz_lines) * draw_height
            painter.drawLine(draw_left, int(y), draw_right, int(y))

        # ---- EJES Y ETIQUETAS ----
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(self.text_color)

        for i in range(num_vert_lines + 1):
            dist = (i / num_vert_lines) * total_distance * self.display_scale
            x = draw_left + (i / num_vert_lines) * draw_width
            unit_label = "cm" if self.display_unit == "cm" else "m"
            painter.drawText(
                int(x) - 25,
                draw_bottom + 5,
                50,
                15,
                Qt.AlignCenter,
                f"{dist:.0f} {unit_label}",
            )

        font.setPointSize(7)
        painter.setFont(font)
        unit_label_axis = "cm" if self.display_unit == "cm" else "m"
        painter.drawText(
            draw_left,
            draw_bottom + 20,
            draw_width,
            15,
            Qt.AlignCenter,
            f"Distancia ({unit_label_axis})",
        )

        for i in range(num_horiz_lines + 1):
            elev = y_max_display - (i / num_horiz_lines) * y_display_range
            y = draw_top + (i / num_horiz_lines) * draw_height
            painter.drawText(
                2,
                int(y) - 8,
                draw_left - 5,
                16,
                Qt.AlignRight | Qt.AlignVCenter,
                f"{elev:.1f}",
            )

        painter.save()
        painter.translate(12, draw_top + draw_height / 2)
        painter.rotate(-90)
        painter.drawText(
            int(-draw_height / 2 - 20),
            0,
            int(draw_height),
            12,
            Qt.AlignCenter,
            "Elevación (m s.n.m.)",
        )
        painter.restore()

        # Guardas extra: evitar divisiones y lecturas fuera de rango
        # si los datos internos cambian durante el paint.
        if total_distance <= 0 or y_display_range <= 0:
            return

        has_horizons = bool(intersected_features) and any(
            (getattr(ifeat, "horizons", None) or []) for ifeat in intersected_features
        )

        # Si edición está activa, dibujamos usando el modelo editado
        edit_points_by_key = None
        if self.edit_enabled and self._edit_tracks_ready:
            edit_points_by_key = self._get_edit_points_by_key()

        # Helper superficie interpolada para manuales
        manual_points = points

        def _interp_surface_elev_at(d):
            if not manual_points:
                return None
            if d <= manual_points[0].distance:
                return manual_points[0].elevation
            if d >= manual_points[-1].distance:
                return manual_points[-1].elevation
            low, high = 0, len(manual_points) - 1
            while high - low > 1:
                mid = (low + high) // 2
                if manual_points[mid].distance <= d:
                    low = mid
                else:
                    high = mid
            p1 = manual_points[low]
            p2 = manual_points[high]
            if p2.distance - p1.distance < 1e-6:
                return p1.elevation
            ratio = (d - p1.distance) / (p2.distance - p1.distance)
            return p1.elevation + ratio * (p2.elevation - p1.elevation)

        # Dibujo horizontes detectados
        if has_horizons:
            for ifeat_idx, ifeat in enumerate(intersected_features):
                horizons = getattr(ifeat, "horizons", None) or []
                if not horizons:
                    continue

                start_d = ifeat.intersection_start
                end_d = ifeat.intersection_end

                if end_d - start_d < 0.01:
                    continue

                elev_start = ifeat.surface_elevation_start
                elev_end = ifeat.surface_elevation_end

                if elev_start is None or elev_end is None:
                    continue

                for h_idx, h in enumerate(horizons):
                    # NOTA: h.top y h.bottom están en PROFUNDIDAD (cm) desde la superficie,
                    # NO son elevaciones en metros. Para convertirlos a elevación:
                    #   top_elev = surface_elev_at_point - h.bottom / 100.0
                    #   bottom_elev = surface_elev_at_point - h.top / 100.0
                    # Esto porque h.top < h.bottom (profundidad), y la elevación decrece
                    # con la profundidad.
                    horizon_path = QPainterPath()
                    segment_points = []

                    # Construimos segment_points como lista (d, top_elev, bottom_elev)
                    if edit_points_by_key is not None:
                        # Usamos top/bottom editados, solo para este horizonte
                        top_key = (ifeat_idx, h_idx, "top")
                        bottom_key = (ifeat_idx, h_idx, "bottom")
                        # Si no existe, caemos a cálculo original
                        top_pts = edit_points_by_key.get(top_key)
                        bottom_pts = edit_points_by_key.get(bottom_key)
                        if top_pts is not None and bottom_pts is not None:
                            # Emparejamos por distance d (misma malla)
                            bottom_map = {d: e for (d, e) in bottom_pts}
                            for d, top_e in top_pts:
                                b_e = bottom_map.get(d)
                                if b_e is None:
                                    continue
                                segment_points.append((d, float(top_e), float(b_e)))
                        else:
                            # cálculo original
                            segment_points = []
                    if not segment_points:
                        # Asegurar los puntos exactos de inicio con elevación real
                        # Convertir profundidad cm a elevación usando superficie interpolada
                        def _horizon_elev_at(d, is_top=True):
                            """Convierte profundidad (cm) a elevación (m).
                            h.top = profundidad techo (menor), h.bottom = profundidad muro (mayor)
                            is_top=True = techo del horizonte (más somero) = surface - h.bottom/100
                            is_top=False = muro del horizonte (más profundo) = surface - h.top/100
                            """
                            surf = _interp_surface_elev_at(d)
                            if surf is None:
                                return None
                            if is_top:
                                return surf - (h.bottom / 100.0)
                            else:
                                return surf - (h.top / 100.0)

                        top_elev_start = _horizon_elev_at(start_d, True)
                        bottom_elev_start = _horizon_elev_at(start_d, False)
                        if top_elev_start is not None and bottom_elev_start is not None:
                            segment_points.append(
                                (start_d, top_elev_start, bottom_elev_start)
                            )

                        for pt in points:
                            try:
                                pt_dist = pt.distance
                                if start_d < pt_dist < end_d:
                                    top_elev = _horizon_elev_at(pt_dist, True)
                                    bottom_elev = _horizon_elev_at(pt_dist, False)
                                    if top_elev is not None and bottom_elev is not None:
                                        segment_points.append(
                                            (pt_dist, top_elev, bottom_elev)
                                        )
                            except Exception:
                                continue

                        # Asegurar los puntos exactos de fin con elevación real
                        if end_d > start_d:
                            top_elev_end = _horizon_elev_at(end_d, True)
                            bottom_elev_end = _horizon_elev_at(end_d, False)
                            if top_elev_end is not None and bottom_elev_end is not None:
                                segment_points.append(
                                    (end_d, top_elev_end, bottom_elev_end)
                                )

                    if len(segment_points) < 2:
                        continue

                    d_first, top_first, _ = segment_points[0]
                    x_first, y_first = map_to_screen(d_first, top_first)
                    horizon_path.moveTo(x_first, y_first)

                    for d, top_el, _ in segment_points[1:]:
                        x, y = map_to_screen(d, top_el)
                        horizon_path.lineTo(x, y)

                    for d, _, bottom_el in reversed(segment_points):
                        x, y = map_to_screen(d, bottom_el)
                        horizon_path.lineTo(x, y)

                    horizon_path.closeSubpath()

                    color = h.color
                    # Gradiente más suave: evitar dark(130) que se ve negro al alejar
                    grad = QLinearGradient(0, draw_top, 0, draw_bottom)
                    grad.setColorAt(0, color.lighter(110))
                    grad.setColorAt(0.5, color)
                    grad.setColorAt(1, color.darker(110))

                    painter.save()
                    painter.setClipRect(draw_left, draw_top, draw_width, draw_height)

                    painter.setBrush(QBrush(grad))
                    painter.setPen(QPen(self.horizon_border_color, 0.5))
                    painter.drawPath(horizon_path)

                    if len(segment_points) > 0:
                        mid_idx = len(segment_points) // 2
                        d_mid, top_mid, bottom_mid = segment_points[mid_idx]
                        el_mid = (top_mid + bottom_mid) / 2
                        x_lab, y_lab = map_to_screen(d_mid, el_mid)

                        label_width = min(
                            80,
                            int(
                                map_dist_to_screen_x(end_d)
                                - map_dist_to_screen_x(start_d)
                            )
                            - 10,
                        )
                        label_width = max(30, label_width)

                        # Calcular espesor en metros
                        thickness_m = (h.bottom - h.top) / 100.0

                        font_label = painter.font()
                        font_label.setPointSize(7)
                        font_label.setBold(True)
                        painter.setFont(font_label)

                        # Mostrar nombre + espesor en dos líneas
                        name_rect = QRectF(
                            x_lab - label_width / 2,
                            y_lab - 10,
                            label_width,
                            12,
                        )
                        painter.fillRect(
                            QRectF(
                                x_lab - label_width / 2 - 1,
                                y_lab - 11,
                                label_width + 2,
                                24,
                            ),
                            QColor(255, 255, 255, 210),
                        )
                        painter.setPen(QColor(20, 20, 20, 200))
                        painter.drawText(name_rect, Qt.AlignCenter, h.name)

                        font_label.setBold(False)
                        font_label.setPointSize(6)
                        painter.setFont(font_label)
                        thickness_rect = QRectF(
                            x_lab - label_width / 2,
                            y_lab + 2,
                            label_width,
                            10,
                        )
                        painter.setPen(QColor(60, 60, 60, 200))
                        painter.drawText(
                            thickness_rect, Qt.AlignCenter, f"{thickness_m:.2f} m"
                        )

                    painter.restore()

                    painter.save()
                    painter.setClipRect(draw_left, draw_top, draw_width, draw_height)
                    # Usar el color original del horizonte (sin oscurecer) para mejor visibilidad
                    painter.setPen(QPen(color, 1.0))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawPath(horizon_path)
                    painter.restore()

        # Dibujo horizontes manuales por tramo
        if self.manual_segments:
            for mseg_idx, mseg in enumerate(self.manual_segments):
                try:
                    start_d = float(mseg.get("start_d"))
                    end_d = float(mseg.get("end_d"))
                    h = mseg.get("horizon")
                except Exception:
                    continue
                if h is None:
                    continue
                if end_d - start_d < 0.01:
                    continue

                # segment_points (d, top_elev, bottom_elev)
                segment_points = []
                for pt in points:
                    pt_dist = float(pt.distance)
                    if start_d <= pt_dist <= end_d:
                        surf_elev = _interp_surface_elev_at(pt_dist)
                        if surf_elev is None:
                            continue
                        top_depth_m = -float(h.top) / 100.0
                        bottom_depth_m = -float(h.bottom) / 100.0
                        segment_points.append(
                            (
                                pt_dist,
                                surf_elev + top_depth_m,
                                surf_elev + bottom_depth_m,
                            )
                        )

                # Si edit_enabled y hay tracks manuales, sobreescribir con edit_points_by_key
                if (
                    self.edit_enabled
                    and edit_points_by_key is not None
                    and segment_points
                    and len(segment_points) >= 2
                ):
                    top_key = ("manual", mseg_idx, h, "top")  # placeholder
                # En lugar de reconstruir por key complejo, reusamos tracks ya calculados
                # a partir de _get_edit_points_by_key, que hoy usa (ifeat_idx,h_idx,kind).
                # Para manuales creamos tracks con h_idx=mseg_idx y ifeat_idx=mseg_idx en build.
                # Como _get_edit_points_by_key no distingue 'source', mapear:
                top_key = (mseg_idx, mseg_idx, "top")
                bottom_key = (mseg_idx, mseg_idx, "bottom")
                # Nota: si por cualquier razón no existen claves, se dibuja con valores actuales (h.top/h.bottom).

                if edit_points_by_key is not None:
                    top_pts = edit_points_by_key.get(top_key)
                    bottom_pts = edit_points_by_key.get(bottom_key)
                    if (
                        top_pts is not None
                        and bottom_pts is not None
                        and len(top_pts) >= 2
                        and len(bottom_pts) >= 2
                    ):
                        bottom_map = {d: e for (d, e) in bottom_pts}
                        new_segment = []
                        for d, top_e in top_pts:
                            b_e = bottom_map.get(d)
                            if b_e is None:
                                continue
                            new_segment.append((d, float(top_e), float(b_e)))
                        if len(new_segment) >= 2:
                            segment_points = new_segment

                if len(segment_points) < 2:
                    continue

                horizon_path = QPainterPath()
                d_first, top_first, _ = segment_points[0]
                x_first, y_first = map_to_screen(d_first, top_first)
                horizon_path.moveTo(x_first, y_first)

                for d, top_el, _ in segment_points[1:]:
                    x, y = map_to_screen(d, top_el)
                    horizon_path.lineTo(x, y)

                for d, _, bottom_el in reversed(segment_points):
                    x, y = map_to_screen(d, bottom_el)
                    horizon_path.lineTo(x, y)

                horizon_path.closeSubpath()

                color = h.color
                grad = QLinearGradient(0, draw_top, 0, draw_bottom)
                grad.setColorAt(0, color.lighter(115))
                grad.setColorAt(0.5, color)
                grad.setColorAt(1, color.darker(130))

                painter.save()
                painter.setClipRect(draw_left, draw_top, draw_width, draw_height)

                painter.setBrush(QBrush(grad))
                painter.setPen(QPen(self.horizon_border_color, 0.8))
                painter.drawPath(horizon_path)

                # Etiqueta con nombre + espesor
                mid_idx = len(segment_points) // 2
                d_mid, top_mid, bottom_mid = segment_points[mid_idx]
                el_mid = (top_mid + bottom_mid) / 2.0
                x_lab, y_lab = map_to_screen(d_mid, el_mid)

                label_width = min(
                    80,
                    int(map_dist_to_screen_x(end_d) - map_dist_to_screen_x(start_d))
                    - 10,
                )
                label_width = max(30, label_width)

                # Calcular espesor en metros
                thickness_m = (h.bottom - h.top) / 100.0

                font_label = painter.font()
                font_label.setPointSize(7)
                font_label.setBold(True)
                painter.setFont(font_label)

                # Mostrar nombre + espesor en dos líneas
                painter.fillRect(
                    QRectF(
                        x_lab - label_width / 2 - 1,
                        y_lab - 11,
                        label_width + 2,
                        24,
                    ),
                    QColor(255, 255, 255, 210),
                )
                name_rect = QRectF(
                    x_lab - label_width / 2,
                    y_lab - 10,
                    label_width,
                    12,
                )
                painter.setPen(QColor(20, 20, 20, 200))
                painter.drawText(name_rect, Qt.AlignCenter, h.name)

                font_label.setBold(False)
                font_label.setPointSize(6)
                painter.setFont(font_label)
                thickness_rect = QRectF(
                    x_lab - label_width / 2,
                    y_lab + 2,
                    label_width,
                    10,
                )
                painter.setPen(QColor(60, 60, 60, 200))
                painter.drawText(thickness_rect, Qt.AlignCenter, f"{thickness_m:.2f} m")

                painter.restore()

                painter.save()
                painter.setClipRect(draw_left, draw_top, draw_width, draw_height)
                # Usar el color original del horizonte (sin oscurecer) para mejor visibilidad
                painter.setPen(QPen(color, 1.0))
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(horizon_path)
                painter.restore()

        # ---- SUPERFICIE (DEM) ----
        surface_path = QPainterPath()
        first_point = data.points[0]
        x0, y0 = map_to_screen(first_point.distance, first_point.elevation)
        surface_path.moveTo(x0, y0)

        for point in points[1:]:
            x, y = map_to_screen(point.distance, point.elevation)
            surface_path.lineTo(x, y)

        painter.save()
        painter.setClipRect(draw_left, draw_top, draw_width, draw_height)

        fill_path = QPainterPath()
        first_pt = points[0]
        x0, y0 = map_to_screen(first_pt.distance, first_pt.elevation)
        fill_path.moveTo(x0, y0)

        for point in points[1:]:
            x, y = map_to_screen(point.distance, point.elevation)
            fill_path.lineTo(x, y)

        last_pt = points[-1]
        x_last, y_bottom = map_to_screen(last_pt.distance, y_min_display)
        fill_path.lineTo(x_last, y_bottom)
        x_first_fill, _ = map_to_screen(first_pt.distance, y_min_display)
        fill_path.lineTo(x_first_fill, y_bottom)
        fill_path.closeSubpath()

        painter.setBrush(QBrush(self.surface_fill))
        painter.setPen(Qt.NoPen)
        painter.drawPath(fill_path)
        painter.restore()

        painter.setPen(QPen(self.surface_color, 2.5))
        painter.drawPath(surface_path)

        # ---- MARCAR INTERSECCIONES ----
        if intersected_features:
            for ifeat in intersected_features:
                try:
                    x_start = (
                        draw_left
                        + (ifeat.intersection_start / total_distance) * draw_width
                    )
                    x_end = (
                        draw_left
                        + (ifeat.intersection_end / total_distance) * draw_width
                    )
                except Exception:
                    continue

                painter.setPen(QPen(QColor(0, 100, 200, 60), 1, Qt.DashLine))
                painter.drawLine(int(x_start), draw_top, int(x_start), draw_bottom)
                painter.drawLine(int(x_end), draw_top, int(x_end), draw_bottom)

                try:
                    feature_text = f"FID:{ifeat.feature.id()}"
                except Exception:
                    feature_text = "FID:?"
                font_feat = painter.font()
                font_feat.setPointSize(7)
                painter.setFont(font_feat)
                painter.setPen(QColor(0, 80, 160, 200))

                painter.drawText(
                    int(x_start),
                    draw_top - 16,
                    max(0, int(x_end - x_start)),
                    14,
                    Qt.AlignCenter,
                    feature_text,
                )

                area_rect = QRectF(x_start, draw_top, x_end - x_start, draw_height)
                painter.fillRect(area_rect, QColor(0, 100, 200, 15))

        # ---- MARCADORES ----
        painter.setPen(QPen(QColor(0, 120, 0), 2))
        painter.setBrush(QBrush(QColor(0, 180, 0)))
        x_start_px, y_start_px = map_to_screen(0, points[0].elevation)
        painter.drawEllipse(int(x_start_px) - 3, int(y_start_px) - 3, 6, 6)

        x_end_px, y_end_px = map_to_screen(total_distance, points[-1].elevation)
        painter.setPen(QPen(QColor(180, 0, 0), 2))
        painter.setBrush(QBrush(QColor(255, 0, 0)))
        painter.drawEllipse(int(x_end_px) - 3, int(y_end_px) - 3, 6, 6)

        # ---- LEYENDA ----
        if has_horizons:
            legend_items = []
            seen_names = set()
            for ifeat in intersected_features:
                for h in getattr(ifeat, "horizons", None) or []:
                    try:
                        if h.name not in seen_names:
                            seen_names.add(h.name)
                            legend_items.append((h.name, h.color))
                    except Exception:
                        continue

            if legend_items:
                legend_x = draw_right - 120
                legend_y = draw_top + 5
                legend_item_height = 16
                legend_width = 115
                legend_height = len(legend_items) * legend_item_height + 10

                legend_bg = QRectF(legend_x, legend_y, legend_width, legend_height)
                painter.fillRect(legend_bg, QColor(255, 255, 255, 220))
                painter.setPen(QPen(QColor(180, 180, 180, 150), 0.5))
                painter.drawRect(legend_bg)

                font_legend = painter.font()
                font_legend.setPointSize(7)
                font_legend.setBold(True)
                painter.setFont(font_legend)
                painter.setPen(QColor(50, 50, 50))
                painter.drawText(
                    int(legend_x + 5),
                    int(legend_y + 1),
                    int(legend_width - 10),
                    14,
                    Qt.AlignLeft | Qt.AlignVCenter,
                    "Horizontes",
                )

                font_legend.setBold(False)
                font_legend.setPointSize(7)
                painter.setFont(font_legend)

                for i, (name, color) in enumerate(legend_items):
                    item_y = legend_y + 16 + i * legend_item_height
                    painter.fillRect(legend_x + 5, item_y + 2, 10, 10, color)
                    painter.setPen(QPen(QColor(100, 100, 100), 0.5))
                    painter.drawRect(legend_x + 5, item_y + 2, 10, 10)
                    painter.setPen(QColor(50, 50, 50))
                    painter.drawText(
                        int(legend_x + 20),
                        int(item_y),
                        int(legend_width - 25),
                        14,
                        Qt.AlignLeft | Qt.AlignVCenter,
                        name,
                    )

        # ---- INFO SUPERIOR ----
        font_info = painter.font()
        font_info.setPointSize(9)
        font_info.setBold(True)
        painter.setFont(font_info)
        painter.setPen(QColor(50, 50, 50))

        horizons_present = "Sí" if has_horizons else "No"
        try:
            entities_count = len(intersected_features)
            dist_total = float(
                getattr(data, "total_distance", total_distance) or total_distance
            )
            info_text = (
                f"Distancia total: {dist_total:.1f} m  |  "
                f"Elevación: {data.min_elevation:.1f} - {data.max_elevation:.1f} m  |  "
                f"Entidades: {entities_count}  |  "
                f"Horizontes: {horizons_present}"
            )
        except Exception:
            info_text = "Perfil DEM"
        painter.drawText(
            draw_left, 5, draw_width, 20, Qt.AlignLeft | Qt.AlignTop, info_text
        )


class DEMProfilePanel(QWidget):
    """Panel horizontal para controlar y visualizar el perfil DEM."""

    requestProfileToolActivation = pyqtSignal()
    rasterLayerChanged = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.profile_map_tool = None
        self.plugin_instance = None
        self.raster_layer = None

        self.cells = []  # grilla de celdas (persistida en sidecar)
        self.current_feature = None
        self.current_layer = None

        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(4)

        control_layout = QHBoxLayout()
        control_layout.setSpacing(6)

        title_label = QLabel("Perfil Topográfico")
        title_label.setStyleSheet(
            "font-weight: bold; font-size: 11px; color: #2c3e50; padding: 2px;"
        )
        control_layout.addWidget(title_label)
        control_layout.addSpacing(8)

        dem_label = QLabel("DEM:")
        dem_label.setStyleSheet("font-size: 10px;")
        control_layout.addWidget(dem_label)
        from qgis.gui import QgsMapLayerComboBox
        from qgis.core import QgsMapLayerProxyModel

        self.dem_combo = QgsMapLayerComboBox()
        self.dem_combo.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.dem_combo.setFixedWidth(170)
        self.dem_combo.layerChanged.connect(self.on_dem_layer_changed)
        control_layout.addWidget(self.dem_combo)

        control_layout.addSpacing(4)

        self.draw_profile_btn = QPushButton("✏️ Dibujar Perfil")
        self.draw_profile_btn.setToolTip(
            "Haga clic para activar el dibujo de perfil.\n"
            "Clic izquierdo para añadir puntos.\n"
            "Clic derecho o doble clic para finalizar."
        )
        self.draw_profile_btn.setCheckable(True)
        self.draw_profile_btn.setFixedSize(130, 28)
        self.draw_profile_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #e67e22;
                color: white;
                font-size: 10px;
                font-weight: bold;
                padding: 4px 10px;
                border-radius: 3px;
                min-width: 96px;
            }
            QPushButton:hover {
                background-color: #d35400;
            }
            QPushButton:checked {
                background-color: #c0392b;
            }
        """
        )
        self.draw_profile_btn.clicked.connect(self.on_draw_profile_clicked)
        control_layout.addWidget(self.draw_profile_btn)

        control_layout.addSpacing(4)
        control_layout.addStretch()

        self.export_profile_btn = QPushButton("📷 Exportar")
        self.export_profile_btn.setToolTip("Exporta el perfil como imagen PNG")
        self.export_profile_btn.setEnabled(False)
        self.export_profile_btn.setFixedSize(100, 28)
        self.export_profile_btn.setStyleSheet(
            "font-size: 10px; padding: 4px 8px; border-radius: 3px;"
        )
        self.export_profile_btn.clicked.connect(self.export_profile_image)
        control_layout.addWidget(self.export_profile_btn)

        self.auto_fit_check = QCheckBox("Ajustar automáticamente")
        self.auto_fit_check.setChecked(True)
        self.auto_fit_check.setStyleSheet("font-size: 10px; padding: 2px;")
        control_layout.addWidget(self.auto_fit_check)

        control_layout.addSpacing(6)

        # Selector de unidad de visualización
        unit_label = QLabel("Unidad:")
        unit_label.setStyleSheet("font-size: 10px;")
        control_layout.addWidget(unit_label)

        from qgis.PyQt.QtWidgets import QComboBox

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["Metros (m)", "Centímetros (cm)"])
        self.unit_combo.setFixedWidth(140)
        self.unit_combo.setToolTip(
            "Cambia la unidad de visualización del eje de distancia"
        )
        self.unit_combo.currentIndexChanged.connect(self.on_unit_changed)
        control_layout.addWidget(self.unit_combo)

        # --- Edición en pantalla (DEM canvas) ---
        self.edit_horizons_check = QCheckBox("Editar horizontes")
        self.edit_horizons_check.setChecked(False)
        self.edit_horizons_check.setStyleSheet("font-size: 10px; padding: 2px;")
        control_layout.addWidget(self.edit_horizons_check)

        self.apply_dem_to_profile_btn = QPushButton("Aplicar al perfil")
        self.apply_dem_to_profile_btn.setEnabled(False)
        self.apply_dem_to_profile_btn.setFixedSize(140, 28)
        self.apply_dem_to_profile_btn.setToolTip(
            "Convierte los cambios hechos en el perfil DEM (arrastre) a top/bottom del horizonte y guarda en la entidad seleccionada."
        )
        self.apply_dem_to_profile_btn.clicked.connect(self.apply_dem_changes_to_profile)
        control_layout.addWidget(self.apply_dem_to_profile_btn)

        # --- Edición de celdas (material por celda) ---
        control_layout.addSpacing(6)

        control_layout.addWidget(QLabel("Material celda:"))

        from qgis.PyQt.QtWidgets import QComboBox

        self.material_combo = QComboBox()
        self.material_combo.addItems(get_material_names())
        self.material_combo.setFixedWidth(130)
        control_layout.addWidget(self.material_combo)

        self.assign_cell_btn = QPushButton("Asignar a celda")
        self.assign_cell_btn.setFixedSize(140, 28)
        self.assign_cell_btn.clicked.connect(self.on_assign_material_to_selected_cell)
        self.assign_cell_btn.setEnabled(False)
        control_layout.addWidget(self.assign_cell_btn)

        main_layout.addLayout(control_layout)

        # Scroll area para navegación del perfil
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        scroll_area.setMinimumHeight(300)

        self.canvas = DEMProfileCanvas()
        self.canvas.set_edit_enabled(False)
        scroll_area.setWidget(self.canvas)
        main_layout.addWidget(scroll_area, 1)

        # Conectar toggle edición
        self.edit_horizons_check.toggled.connect(self.on_edit_horizons_toggled)

        # Marcar cambios para habilitar botón aplicar
        self.canvas.edit_changed.connect(self.on_dem_edit_changed)

        status_layout = QHBoxLayout()
        self.status_label = QLabel(
            "Listo. Seleccione un DEM y dibuje una línea en el mapa."
        )
        self.status_label.setStyleSheet(
            "color: #7f8c8d; font-style: italic; font-size: 9px;"
        )
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()

        self.coord_label = QLabel("")
        self.coord_label.setStyleSheet("color: #7f8c8d; font-size: 9px;")
        status_layout.addWidget(self.coord_label)

        main_layout.addLayout(status_layout)
        self.setLayout(main_layout)

        self._update_button_states()

    def _update_button_states(self):
        has_data = bool(
            self.canvas.profile_data is not None
            and getattr(self.canvas.profile_data, "points", None)
        )
        self.export_profile_btn.setEnabled(has_data)

        has_dem = self.dem_combo.currentLayer() is not None
        if not has_dem and self.draw_profile_btn.isChecked():
            self.draw_profile_btn.blockSignals(True)
            self.draw_profile_btn.setChecked(False)
            self.draw_profile_btn.blockSignals(False)
        self.draw_profile_btn.setEnabled(has_dem)

    def on_dem_layer_changed(self, layer):
        self.raster_layer = layer
        self._update_button_states()
        self.rasterLayerChanged.emit(layer)

        if not layer:
            self.cells = []
            self.canvas.set_cells(self.cells)
            self.assign_cell_btn.setEnabled(False)

        if layer:
            self.status_label.setText(
                f"DEM seleccionado: {layer.name()}. Dibuje una línea en el mapa."
            )
        else:
            self.status_label.setText("Seleccione un TIFF DEM para comenzar.")
            if self.draw_profile_btn.isChecked():
                self.draw_profile_btn.blockSignals(True)
                self.draw_profile_btn.setChecked(False)
                self.draw_profile_btn.blockSignals(False)
                if self.plugin_instance:
                    self.plugin_instance.deactivate_profile_tool()

        if self.profile_map_tool:
            self.profile_map_tool.set_raster_layer(layer)

    def on_draw_profile_clicked(self, checked):
        if checked:
            if self.plugin_instance:
                if self.plugin_instance.panel and hasattr(
                    self.plugin_instance.panel, "dem_profile_btn"
                ):
                    self.plugin_instance.panel.dem_profile_btn.blockSignals(True)
                    self.plugin_instance.panel.dem_profile_btn.setChecked(True)
                    self.plugin_instance.panel.dem_profile_btn.blockSignals(False)
                self.plugin_instance.activate_profile_tool()
            else:
                self.requestProfileToolActivation.emit()
        else:
            if self.plugin_instance:
                if self.plugin_instance.panel and hasattr(
                    self.plugin_instance.panel, "dem_profile_btn"
                ):
                    self.plugin_instance.panel.dem_profile_btn.blockSignals(True)
                    self.plugin_instance.panel.dem_profile_btn.setChecked(False)
                    self.plugin_instance.panel.dem_profile_btn.blockSignals(False)
                self.plugin_instance.deactivate_profile_tool()

    def on_edit_horizons_toggled(self, checked: bool):
        # Toggle solo afecta a la interacción dentro del canvas DEM.
        try:
            self.canvas.set_edit_enabled(checked)
            self.apply_dem_to_profile_btn.setEnabled(bool(checked))
        except Exception:
            # No romper el UI si hay un error inesperado.
            self.edit_horizons_check.setChecked(False)

    def on_profile_complete(self, profile_data):
        self.canvas.set_profile_data(profile_data)
        self._update_button_states()

        # Cargar cells desde el sidecar del feature actual (si existe)
        try:
            if self.current_feature is not None and self.current_layer is not None:
                self.cells = (
                    HorizonManager.get_profile_cells(
                        self.current_feature, self.current_layer
                    )
                    or []
                )
                self.canvas.set_cells(self.cells)
            else:
                self.cells = []
                self.canvas.set_cells(self.cells)
        except Exception:
            self.cells = []
            self.canvas.set_cells(self.cells)

        # Activar asignación si existe grilla
        self.assign_cell_btn.setEnabled(bool(self.cells))

        if profile_data and profile_data.points:
            total_horizons = sum(
                len(ifeat.horizons) for ifeat in profile_data.intersected_features
            )
            self.status_label.setText(
                f"Perfil generado: {profile_data.total_distance:.1f}m, "
                f"{len(profile_data.intersected_features)} entidades, "
                f"{total_horizons} horizontes."
            )

            if hasattr(profile_data, "diagnostic") and profile_data.diagnostic.steps:
                print("=" * 60)
                print("DIAGNÓSTICO DE MUESTREO DEM (PERFIL EXITOSO):")
                print("=" * 60)
                print(profile_data.diagnostic.get_summary())
                print("=" * 60)
        else:
            diag_msg = ""
            if hasattr(profile_data, "diagnostic") and profile_data.diagnostic.steps:
                for step in reversed(profile_data.diagnostic.steps):
                    if step["step"] == "Muestreo DEM" and not step["success"]:
                        diag_msg = step["message"]
                        break
                    if step["step"] == "Superposición espacial" and not step["success"]:
                        diag_msg = step["message"]
                        break
                    if (
                        step["step"] == "Interpolación de puntos"
                        and not step["success"]
                    ):
                        diag_msg = step["message"]
                        break
                    if step["step"] == "Validación raster" and not step["success"]:
                        diag_msg = step["message"]
                        break
                    if step["step"] == "Validación polilínea" and not step["success"]:
                        diag_msg = step["message"]
                        break

            if diag_msg:
                self.status_label.setText(
                    f"No se pudo generar el perfil.\nDetalle: {diag_msg}\n"
                    f"Vea la consola de QGIS para el diagnóstico completo."
                )
                if hasattr(profile_data, "diagnostic"):
                    print("=" * 60)
                    print("DIAGNÓSTICO DE MUESTREO DEM (PERFIL FALLIDO):")
                    print("=" * 60)
                    print(profile_data.diagnostic.get_summary())
                    print("=" * 60)
            else:
                self.status_label.setText(
                    "No se pudo generar el perfil. Verifique que el DEM y la línea se superpongan."
                )

        self.draw_profile_btn.blockSignals(True)
        self.draw_profile_btn.setChecked(False)
        self.draw_profile_btn.blockSignals(False)

        if self.plugin_instance and hasattr(self.plugin_instance, "panel"):
            panel = self.plugin_instance.panel
            if panel and hasattr(panel, "dem_profile_btn"):
                panel.dem_profile_btn.blockSignals(True)
                panel.dem_profile_btn.setChecked(False)
                panel.dem_profile_btn.blockSignals(False)

    def export_profile_image(self):
        if not self.canvas.profile_data or not self.canvas.profile_data.points:
            QMessageBox.warning(self, "Sin datos", "No hay perfil para exportar.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar Perfil Topográfico como Imagen",
            "perfil_topografico.png",
            "Imágenes (*.png *.jpg *.jpeg)",
        )

        if file_path:
            success = self.canvas.save_image(file_path)
            if success:
                QMessageBox.information(
                    self, "Éxito", f"Imagen guardada en: {file_path}"
                )
            else:
                QMessageBox.critical(self, "Error", "No se pudo guardar la imagen.")

    def on_unit_changed(self, index):
        """Cambia la unidad de visualización del canvas."""
        if index == 0:  # Metros
            self.canvas.display_unit = "m"
            self.canvas.display_scale = 1.0
            # Restaurar tamaño normal del canvas
            self.canvas.setMinimumSize(400, 250)
            self.canvas.resize(400, 250)
        else:  # Centímetros - aumentar tamaño para ver más detalle
            self.canvas.display_unit = "cm"
            self.canvas.display_scale = 100.0
            # Aumentar tamaño del canvas para zoom en horizontes
            self.canvas.setMinimumSize(800, 600)
            self.canvas.resize(800, 600)
        self.canvas.update()

    def on_dem_edit_changed(self):
        # Habilitar botón solo cuando hay datos para aplicar
        has_profile = bool(
            self.canvas.profile_data
            and getattr(self.canvas.profile_data, "points", None)
        )
        self.apply_dem_to_profile_btn.setEnabled(
            self.edit_horizons_check.isChecked() and has_profile
        )

    def on_assign_material_to_selected_cell(self):
        """
        Asigna el material seleccionado a la celda actualmente seleccionada.
        """
        try:
            if not hasattr(self.canvas, "assign_material_to_selected_cell"):
                return

            if not self.canvas.profile_data:
                return

            mat = self.material_combo.currentText().strip()
            if not mat:
                return

            changed = self.canvas.assign_material_to_selected_cell(mat)
            if changed:
                # refrescar UI/botón de aplicar
                self.canvas.update()
                self.apply_dem_to_profile_btn.setEnabled(
                    self.edit_horizons_check.isChecked()
                )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo asignar material: {e}")

    def apply_dem_changes_to_profile(self):
        # Persistir cambios desde el canvas DEM a la entidad seleccionada (igual que edafológico)
        try:
            plugin = self.plugin_instance
            panel = getattr(plugin, "panel", None)
            if (
                not panel
                or not getattr(panel, "current_feature", None)
                or not getattr(panel, "current_layer", None)
            ):
                QMessageBox.warning(
                    self,
                    "Sin entidad",
                    "Seleccione primero una entidad en el panel edafológico.",
                )
                return

            if not self.canvas.profile_data or not self.canvas._edit_tracks_ready:
                QMessageBox.warning(
                    self,
                    "Sin cambios",
                    "Genere un perfil DEM y active la edición de horizontes antes de aplicar.",
                )
                return

            # Requiere que exista una correspondencia por índice de horizonte en panel.horizons.
            if not panel.horizons:
                QMessageBox.warning(
                    self,
                    "Sin horizontes",
                    "La entidad seleccionada no tiene horizontes cargados. Añada/Genere un perfil edafológico primero o aplique una plantilla.",
                )
                return

            # Convertir tracks editados (elevaciones) a top/bottom cm promedio.
            # Nota: el canvas usa (ifeat_idx,h_idx,kind). Para compatibilidad con formato actual,
            # mapeamos por índice de horizonte (h_idx) y promediamos top/bottom editados a lo largo del tramo.
            edit_points_by_key = (
                self.canvas._get_edit_points_by_key()
                if self.canvas.edit_enabled
                else None
            )
            if not edit_points_by_key:
                QMessageBox.warning(
                    self, "Error", "No se pudieron leer los puntos editados."
                )
                return

            updated_horizons = []
            # Para cada horizonte en el panel, usar el track (kind) del primer ifeat_idx existente.
            # Tomamos el mínimo ifeat_idx con datos para robustez.
            # Esto asume que la edición fue realizada sobre el mismo conjunto de horizontes que está en panel.
            # (Si el perfil DEM corta múltiples entidades intersectadas, pero tú guardas solo la seleccionada, este mapeo se conserva por índice.)
            available_ifeat = sorted(
                {k[0] for k in edit_points_by_key.keys() if k[2] in ("top", "bottom")}
            )
            if not available_ifeat:
                QMessageBox.warning(self, "Error", "No hay tracks editables.")
                return
            ifeat_use = available_ifeat[0]

            # Para convertir elevación de horizonte -> profundidades cm, necesitamos elevación superficial del tramo.
            # En el engine, la profundidad se calculó como:
            #   top_depth = point.elevation - horizon.bottom
            #   bottom_depth = point.elevation - horizon.top
            # Invirtiendo para top/bottom profundidad promedio:
            #   horizon.bottom = point.elevation - top_depth_cm/100
            #   horizon.top = point.elevation - bottom_depth_cm/100
            # Pero aquí tenemos top/bottom editados en elevación del horizonte.
            # Entonces:
            #   top_depth = point.elev - top_horizon_depth_elev? (en canvas usamos h_top_elev, h_bottom_elev como elevaciones reales de top/bottom)
            # Y el panel almacena top/bottom profundidades positivas en cm.
            # Profundidad(cm) = (surface_elev - horizon_elev)*100.
            # Usamos superficie promedio sobre los puntos del tramo para cada h.
            # Para eso, reconstruimos superficie promedio usando profile_data y la malla (track points 'd').

            prof = self.canvas.profile_data
            surf_elev_min = prof.min_elevation
            surf_elev_max = prof.max_elevation
            # Ajuste conservador: para el promedio de superficie por el tramo, usamos elevación promedio de profile_data.points.
            if not getattr(prof, "points", None) or len(prof.points) == 0:
                QMessageBox.warning(self, "Error", "Perfil DEM sin puntos.")
                return
            # Promedio sobre todos los puntos muestreados (aprox.)
            surf_avg = sum(p.elevation for p in prof.points) / len(prof.points)

            for h_idx, panel_h in enumerate(panel.horizons):
                top_key = (ifeat_use, h_idx, "top")
                bottom_key = (ifeat_use, h_idx, "bottom")
                top_pts = edit_points_by_key.get(top_key)
                bottom_pts = edit_points_by_key.get(bottom_key)
                if not top_pts or not bottom_pts:
                    # Si no hay tracks para este índice, conservar como está
                    updated_horizons.append(panel_h)
                    continue

                # Promediar elevaciones editadas a lo largo de los vértices
                avg_top_elev = sum(e for _, e in top_pts) / len(top_pts)
                avg_bottom_elev = sum(e for _, e in bottom_pts) / len(bottom_pts)

                # Convertir a profundidades cm: depth = (surface_elev - horizon_elev)*100
                top_depth_cm = (surf_avg - avg_top_elev) * 100.0
                bottom_depth_cm = (surf_avg - avg_bottom_elev) * 100.0

                # Asegurar orden: top < bottom, y no negativos
                top_depth_cm = max(0.0, float(top_depth_cm))
                bottom_depth_cm = max(top_depth_cm, float(bottom_depth_cm))

                # Actualizar HorizonData (mantener propiedades)
                new_h = panel_h
                new_h.top = top_depth_cm
                new_h.bottom = bottom_depth_cm
                updated_horizons.append(new_h)

            # Re-encadenar si auto_chain está activo en el panel principal
            if (
                hasattr(panel, "auto_chain_check")
                and panel.auto_chain_check.isChecked()
            ):
                from ..core.horizon_manager import HorizonManager

                updated_horizons = HorizonManager.rechain_horizons(updated_horizons)

            # Guardar en la entidad seleccionada
            from ..core.horizon_manager import HorizonManager

            profile_id = panel.profile_id_edit.text().strip()
            description = panel.profile_desc_edit.toPlainText().strip()
            # Guardar también cells (grilla de materiales) independientemente del perfil edafológico.
            self.cells = getattr(self.canvas, "cells", None) or []
            success = HorizonManager.save_profile_data(
                panel.current_feature,
                panel.current_layer,
                profile_id,
                description,
                updated_horizons,
                cells=self.cells,
            )
            if not success:
                QMessageBox.critical(
                    self,
                    "Error",
                    "No se pudo guardar el perfil actualizado en la entidad seleccionada.",
                )
                return

            # Actualizar UI del panel principal
            panel.horizons = updated_horizons
            panel.update_ui()
            panel.load_explorer_features()
            panel.horizonsChanged.emit(panel.horizons)

            self.apply_dem_to_profile_btn.setEnabled(False)
            self.edit_horizons_check.setChecked(False)
            self.canvas.set_edit_enabled(False)

            QMessageBox.information(
                self,
                "Éxito",
                "Horizontes DEM aplicados y guardados en la entidad seleccionada.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Fallo al aplicar cambios DEM: {e}")

    def refresh(self):
        self.canvas.update()

    def set_status_coords(self, distance, elevation):
        if distance is not None and elevation is not None:
            self.coord_label.setText(f"Dist: {distance:.1f}m, Elev: {elevation:.1f}m")
        else:
            self.coord_label.setText("")
