# -*- coding: utf-8 -*-
"""
Motor de perfiles topográficos sobre DEM.
Permite muestrear un raster DEM a lo largo de una línea poligonal,
detectar entidades vectoriales que intersectan la línea,
y posicionar horizontes de suelo bajo la superficie del DEM.

Incluye sistema de diagnóstico para depurar fallos en el muestreo.
"""

import math
import numpy as np
import traceback

from qgis.core import (
    QgsRasterLayer,
    QgsGeometry,
    QgsPointXY,
    QgsFeature,
    QgsVectorLayer,
    QgsProject,
    QgsRasterDataProvider,
    QgsRasterBandStats,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsMapLayer,
    QgsRectangle,
)
from qgis.PyQt.QtCore import QPointF
from qgis.PyQt.QtGui import QColor

from .horizon_manager import HorizonManager
from .profile_engine import HorizonData


class RasterDiagnostic:
    """
    Almacena información detallada de diagnóstico sobre el proceso
    de muestreo del raster. Ayuda a depurar por qué falla la extracción
    de elevaciones del DEM.
    """

    def __init__(self):
        self.steps = []
        self.errors = []
        self.warnings = []
        self.raster_info = {}
        self.transform_info = {}
        self.overlap_check_info = {}
        self.total_points_tried = 0
        self.total_points_success = 0
        self.total_points_failed = 0

    def add_step(self, step_name, success, message=""):
        self.steps.append(
            {
                "step": step_name,
                "success": success,
                "message": message,
            }
        )

    def add_error(self, context, error_msg):
        self.errors.append(
            {
                "context": context,
                "error": str(error_msg),
                "traceback": traceback.format_exc(),
            }
        )

    def add_warning(self, context, message):
        self.warnings.append(
            {
                "context": context,
                "message": message,
            }
        )

    def set_raster_info(self, info_dict):
        self.raster_info = info_dict

    def set_transform_info(self, info_dict):
        self.transform_info = info_dict

    def set_overlap_check_info(self, info_dict):
        self.overlap_check_info = info_dict

    def get_summary(self):
        lines = []
        lines.append("=== DIAGNÓSTICO DE MUESTREO DEM ===")
        lines.append("")

        lines.append(f"Puntos intentados: {self.total_points_tried}")
        lines.append(f"Puntos exitosos: {self.total_points_success}")
        lines.append(f"Puntos fallidos: {self.total_points_failed}")
        lines.append("")

        if self.errors:
            lines.append(f"ERRORES ({len(self.errors)}):")
            for e in self.errors:
                lines.append(f"  [{e['context']}] {e['error']}")
            lines.append("")

        if self.warnings:
            lines.append(f"ADVERTENCIAS ({len(self.warnings)}):")
            for w in self.warnings:
                lines.append(f"  [{w['context']}] {w['message']}")
            lines.append("")

        if self.raster_info:
            lines.append("Información del raster:")
            for k, v in self.raster_info.items():
                if isinstance(v, dict):
                    lines.append(f"  {k}:")
                    for sk, sv in v.items():
                        lines.append(f"    {sk}: {sv}")
                else:
                    lines.append(f"  {k}: {v}")
            lines.append("")

        if self.transform_info:
            lines.append("Transformación de coordenadas:")
            for k, v in self.transform_info.items():
                lines.append(f"  {k}: {v}")
            lines.append("")

        if self.overlap_check_info:
            lines.append("Verificación de superposición:")
            for k, v in self.overlap_check_info.items():
                lines.append(f"  {k}: {v}")

        if self.steps:
            lines.append("")
            lines.append("Pasos del proceso:")
            for s in self.steps:
                status = "✓" if s["success"] else "✗"
                msg = f" - {s['message']}" if s["message"] else ""
                lines.append(f"  {status} {s['step']}{msg}")

        lines.append("")
        lines.append("=== FIN DIAGNÓSTICO ===")
        return "\n".join(lines)

    def print_summary(self):
        print(self.get_summary())


class DEMProfilePoint:
    """Punto muestreado del perfil con elevación y distancia acumulada."""

    def __init__(self, x, y, elevation, distance):
        self.x = x
        self.y = y
        self.elevation = elevation
        self.distance = distance
        self.horizons = []


class IntersectedFeature:
    """Entidad vectorial que intersecta la línea del perfil."""

    def __init__(self, feature, layer):
        self.feature = feature
        self.layer = layer
        self.horizons = []
        self.intersection_start = 0.0
        self.intersection_end = 0.0
        self.surface_elevation_start = 0.0
        self.surface_elevation_end = 0.0


class DEMProfileData:
    """Contenedor de todos los datos del perfil DEM."""

    def __init__(self):
        self.points = []
        self.total_distance = 0.0
        self.min_elevation = float("inf")
        self.max_elevation = float("-inf")
        self.intersected_features = []
        self.polyline = []
        self.diagnostic = RasterDiagnostic()


class DEMProfileEngine:
    """Motor de análisis de perfiles sobre DEM."""

    DEFAULT_SAMPLE_POINTS = 500

    @staticmethod
    def get_raster_bands_info(raster_layer):
        if not raster_layer or not isinstance(raster_layer, QgsRasterLayer):
            return None
        provider = raster_layer.dataProvider()
        if not provider:
            return None
        bands_info = {}
        for band in range(1, provider.bandCount() + 1):
            try:
                stats = provider.bandStatistics(band, QgsRasterBandStats.All)
                bands_info[band] = {
                    "min": stats.minimumValue,
                    "max": stats.maximumValue,
                    "mean": stats.mean,
                    "std": stats.stdDev,
                    "name": provider.bandName(band),
                }
            except Exception:
                bands_info[band] = {
                    "min": None,
                    "max": None,
                    "mean": None,
                    "std": None,
                    "name": f"Band {band}",
                }
        return bands_info

    @staticmethod
    def sample_raster_at_point(raster_layer, point, band=1):
        """Muestrea usando provider.identify() - método estándar."""
        if not raster_layer or not isinstance(raster_layer, QgsRasterLayer):
            return None
        provider = raster_layer.dataProvider()
        if not provider:
            return None
        try:
            result = provider.identify(point, QgsRasterDataProvider.IdentifyFormatValue)
            if result and result.isValid():
                val = result.results().get(band)
                if val is not None and not np.isnan(val) and np.isfinite(val):
                    return float(val)
            return None
        except Exception:
            return None

    @staticmethod
    def sample_raster_sample_method(raster_layer, point, band=1):
        """Muestrea usando provider.sample() - método directo."""
        if not raster_layer or not isinstance(raster_layer, QgsRasterLayer):
            return None
        provider = raster_layer.dataProvider()
        if not provider:
            return None
        try:
            val, success = provider.sample(point, band)
            if success and val is not None and not np.isnan(val) and np.isfinite(val):
                return float(val)
            return None
        except Exception:
            return None

    @staticmethod
    def sample_raster_robust(raster_layer, point, band=1):
        """
        Intenta muestrear usando solo métodos SEGUROS que no crashean.
        Estrategias probadas en orden:
        1. provider.sample() - método directo, muy seguro
        2. provider.identify() - método estándar
        NO se usa provider.block() porque puede cargar el raster completo en memoria.
        """
        # Método 1: sample (directo, más seguro)
        val = DEMProfileEngine.sample_raster_sample_method(raster_layer, point, band)
        if val is not None:
            return val

        # Método 2: identify (estándar)
        val = DEMProfileEngine.sample_raster_at_point(raster_layer, point, band)
        if val is not None:
            return val

        return None

    @staticmethod
    def interpolate_elevation_at_distance(profile_points, target_distance):
        if not profile_points:
            return None
        if target_distance <= profile_points[0].distance:
            return profile_points[0].elevation
        if target_distance >= profile_points[-1].distance:
            return profile_points[-1].elevation

        low, high = 0, len(profile_points) - 1
        while high - low > 1:
            mid = (low + high) // 2
            if profile_points[mid].distance <= target_distance:
                low = mid
            else:
                high = mid

        p1 = profile_points[low]
        p2 = profile_points[high]

        if p2.distance - p1.distance < 0.001:
            return p1.elevation

        ratio = (target_distance - p1.distance) / (p2.distance - p1.distance)
        return p1.elevation + ratio * (p2.elevation - p1.elevation)

    @staticmethod
    def compute_polyline_distances(points):
        distances = [0.0]
        for i in range(1, len(points)):
            dx = points[i].x() - points[i - 1].x()
            dy = points[i].y() - points[i - 1].y()
            d = math.sqrt(dx * dx + dy * dy)
            distances.append(distances[-1] + d)
        return distances

    @staticmethod
    def interpolate_points_along_line(points, num_samples=500):
        if not points or len(points) < 2:
            return []

        if len(points) == 2:
            p1, p2 = points[0], points[1]
            dx = p2.x() - p1.x()
            dy = p2.y() - p1.y()
            dist = math.sqrt(dx * dx + dy * dy)
            sampled = []
            for i in range(num_samples):
                ratio = i / (num_samples - 1) if num_samples > 1 else 0.5
                x = p1.x() + ratio * dx
                y = p1.y() + ratio * dy
                d = ratio * dist
                sampled.append((QgsPointXY(x, y), d))
            return sampled

        distances = DEMProfileEngine.compute_polyline_distances(points)
        total_distance = distances[-1]

        if total_distance <= 0:
            return [(points[0], 0.0)]

        sampled = []
        for i in range(num_samples):
            target_d = (
                (i / (num_samples - 1)) * total_distance
                if num_samples > 1
                else total_distance / 2
            )
            for seg_idx in range(1, len(points)):
                if distances[seg_idx] >= target_d:
                    p1 = points[seg_idx - 1]
                    p2 = points[seg_idx]
                    seg_start_d = distances[seg_idx - 1]
                    seg_len = distances[seg_idx] - distances[seg_idx - 1]
                    if seg_len < 0.0001:
                        sampled.append((p1, target_d))
                    else:
                        ratio = (target_d - seg_start_d) / seg_len
                        x = p1.x() + ratio * (p2.x() - p1.x())
                        y = p1.y() + ratio * (p2.y() - p1.y())
                        sampled.append((QgsPointXY(x, y), target_d))
                    break
        return sampled

    @staticmethod
    def _check_raster_extent_overlap(raster_layer, polyline_points, map_crs=None):
        """
        Verifica superposición entre línea y raster.
        Retorna (bool, dict) - la tupla evita ambigüedad.
        """
        info = {}

        try:
            raster_extent = raster_layer.extent()
            info["raster_extent"] = str(raster_extent)

            raster_crs = raster_layer.crs()
            info["raster_crs"] = (
                raster_crs.authid() if raster_crs.isValid() else "unknown"
            )

            if map_crs is None:
                map_crs = QgsProject.instance().crs()
            info["map_crs"] = map_crs.authid() if map_crs.isValid() else "unknown"

            # Transformar puntos al CRS del raster
            coord_transform = None
            if raster_crs != map_crs:
                try:
                    coord_transform = QgsCoordinateTransform(
                        map_crs, raster_crs, QgsProject.instance()
                    )
                except Exception:
                    coord_transform = None

            all_x, all_y = [], []
            for pt in polyline_points:
                if coord_transform:
                    try:
                        pt_t = coord_transform.transform(pt)
                    except Exception:
                        pt_t = pt
                else:
                    pt_t = pt
                all_x.append(pt_t.x())
                all_y.append(pt_t.y())

            if not all_x:
                return True, info

            min_x, max_x = min(all_x), max(all_x)
            min_y, max_y = min(all_y), max(all_y)
            line_rect = QgsRectangle(min_x, min_y, max_x, max_y)
            info["line_bbox"] = str(line_rect)

            overlaps = raster_extent.intersects(line_rect)
            info["overlaps"] = overlaps

            contains_any = any(
                raster_extent.contains(QgsPointXY(x, y)) for x, y in zip(all_x, all_y)
            )
            info["raster_contains_any_point"] = contains_any

            return overlaps, info

        except Exception as e:
            info["error"] = str(e)
            return True, info

    @staticmethod
    def _gather_raster_diagnostics(raster_layer, map_crs=None):
        """Reúne información básica del raster."""
        info = {}
        try:
            if not raster_layer or not isinstance(raster_layer, QgsRasterLayer):
                info["valid"] = False
                return info

            info["name"] = raster_layer.name()
            info["source"] = raster_layer.source()
            info["valid"] = raster_layer.isValid()

            provider = raster_layer.dataProvider()
            info["has_provider"] = provider is not None

            if provider:
                info["provider_type"] = provider.name()
                info["band_count"] = provider.bandCount()
                try:
                    crs = raster_layer.crs()
                    info["crs"] = crs.authid() if crs.isValid() else "invalid"
                except Exception:
                    info["crs"] = "error"

                extent = raster_layer.extent()
                info["extent"] = {
                    "xmin": extent.xMinimum(),
                    "ymin": extent.yMinimum(),
                    "xmax": extent.xMaximum(),
                    "ymax": extent.yMaximum(),
                }

            if map_crs:
                info["map_crs"] = map_crs.authid() if map_crs.isValid() else "invalid"

        except Exception as e:
            info["error"] = str(e)

        return info

    @staticmethod
    def generate_profile(
        raster_layer, polyline_points, vector_layers=None, num_samples=500, map_crs=None
    ):
        """
        Genera un perfil completo: muestrea el DEM, detecta intersecciones con vectores,
        y posiciona horizontes. Versión optimizada para evitar crashes.
        """
        profile_data = DEMProfileData()
        profile_data.polyline = polyline_points
        diagnostic = profile_data.diagnostic

        diagnostic.add_step("Inicio", True, f"Muestreo con {num_samples} puntos")

        # Validaciones tempranas
        if not polyline_points or len(polyline_points) < 2:
            diagnostic.add_step("Validación polilínea", False, "Menos de 2 puntos")
            return profile_data

        diagnostic.add_step(
            "Validación polilínea", True, f"{len(polyline_points)} puntos"
        )

        if not raster_layer or not isinstance(raster_layer, QgsRasterLayer):
            diagnostic.add_step("Validación raster", False, "No es QgsRasterLayer")
            return profile_data

        provider = raster_layer.dataProvider()
        if not provider:
            diagnostic.add_step("Validación raster", False, "Sin dataProvider")
            return profile_data

        diagnostic.add_step("Validación raster", True, f"{raster_layer.name()}")

        # Info de diagnóstico
        raster_diag_info = DEMProfileEngine._gather_raster_diagnostics(
            raster_layer, map_crs
        )
        diagnostic.set_raster_info(raster_diag_info)

        # Verificar superposición
        overlaps, overlap_info = DEMProfileEngine._check_raster_extent_overlap(
            raster_layer, polyline_points, map_crs
        )
        diagnostic.set_overlap_check_info(overlap_info)

        if not overlaps:
            diagnostic.add_step(
                "Superposición espacial",
                False,
                f"Línea no superpuesta. CRS raster: {raster_diag_info.get('crs','?')}",
            )
            return profile_data

        diagnostic.add_step("Superposición espacial", True, "OK")

        # Interpolar puntos
        sampled_points = DEMProfileEngine.interpolate_points_along_line(
            polyline_points, num_samples
        )

        if not sampled_points:
            diagnostic.add_step("Interpolación", False, "Sin puntos interpolados")
            return profile_data

        diagnostic.add_step("Interpolación", True, f"{len(sampled_points)} puntos")

        # Transformación CRS
        raster_crs = raster_layer.crs()
        if map_crs is None:
            map_crs = QgsProject.instance().crs()

        coord_transform = None
        transform_info = {}

        if raster_crs and map_crs:
            transform_info["raster_crs"] = (
                raster_crs.authid() if raster_crs.isValid() else "invalid"
            )
            transform_info["map_crs"] = (
                map_crs.authid() if map_crs.isValid() else "invalid"
            )

            if raster_crs != map_crs:
                try:
                    coord_transform = QgsCoordinateTransform(
                        map_crs, raster_crs, QgsProject.instance()
                    )
                    transform_info["transform_created"] = True
                except Exception as e:
                    transform_info["transform_created"] = False
                    transform_info["transform_error"] = str(e)

        diagnostic.set_transform_info(transform_info)
        diagnostic.total_points_tried = len(sampled_points)

        # Muestrear DEM (solo métodos seguros)
        elevations = []
        valid_points = []

        for qgs_point, distance in sampled_points:
            sample_point = qgs_point
            if coord_transform is not None:
                try:
                    sample_point = coord_transform.transform(qgs_point)
                except Exception:
                    sample_point = qgs_point

            # Solo métodos seguros: sample() y identify()
            elevation = DEMProfileEngine.sample_raster_robust(
                raster_layer, sample_point
            )

            if elevation is not None:
                profile_point = DEMProfilePoint(
                    qgs_point.x(), qgs_point.y(), elevation, distance
                )
                valid_points.append(profile_point)
                elevations.append(elevation)
                diagnostic.total_points_success += 1
            else:
                diagnostic.total_points_failed += 1

        profile_data.points = valid_points

        if valid_points:
            profile_data.total_distance = valid_points[-1].distance
            profile_data.min_elevation = min(elevations)
            profile_data.max_elevation = max(elevations)
            diagnostic.add_step(
                "Muestreo DEM",
                True,
                f"{len(valid_points)}/{len(sampled_points)} pts "
                f"Elev: {profile_data.min_elevation:.1f}-{profile_data.max_elevation:.1f}",
            )
        else:
            diagnostic.add_step(
                "Muestreo DEM", False, f"0/{len(sampled_points)} pts exitosos"
            )

        # Capas vectoriales (auto-descubrimiento)
        if vector_layers is None:
            vector_layers = []
            for layer in QgsProject.instance().mapLayers().values():
                if isinstance(layer, QgsVectorLayer) and layer.geometryType() == 2:
                    if layer.isValid():
                        vector_layers.append(layer)

        # Intersecciones vectoriales
        if vector_layers and valid_points:
            line_geom = QgsGeometry.fromPolylineXY(polyline_points)

            for vlayer in vector_layers:
                # Nunca asumimos que "vector_layers" es solo vector.
                # En tu caso llegó un QgsRasterLayer, causando AttributeError en fields().
                try:
                    if (
                        not vlayer
                        or not vlayer.isValid()
                        or not isinstance(vlayer, QgsVectorLayer)
                    ):
                        continue
                except RuntimeError:
                    continue

                try:
                    idx = vlayer.fields().indexOf("edafo_id")
                    if idx == -1:
                        continue

                    for feature in vlayer.getFeatures():
                        geom = feature.geometry()
                        if not geom:
                            continue

                        if line_geom.intersects(geom):
                            horizons = HorizonManager.get_horizons(feature, vlayer)
                            if not horizons:
                                continue

                            intersection = line_geom.intersection(geom)
                            if intersection.isEmpty() or not intersection.isGeosValid():
                                continue

                            intersected_feat = IntersectedFeature(feature, vlayer)
                            intersected_feat.horizons = horizons

                            if intersection.type() == 1:
                                intersect_points = intersection.asPolyline()
                                if intersect_points:
                                    start_d, end_d = (
                                        DEMProfileEngine._find_intersection_distances(
                                            valid_points, intersect_points
                                        )
                                    )
                                    intersected_feat.intersection_start = start_d
                                    intersected_feat.intersection_end = end_d
                                    intersected_feat.surface_elevation_start = DEMProfileEngine.interpolate_elevation_at_distance(
                                        valid_points, start_d
                                    )
                                    intersected_feat.surface_elevation_end = DEMProfileEngine.interpolate_elevation_at_distance(
                                        valid_points, end_d
                                    )
                                    DEMProfileEngine._assign_horizons_to_points(
                                        valid_points, intersected_feat
                                    )
                                    profile_data.intersected_features.append(
                                        intersected_feat
                                    )

                except RuntimeError:
                    continue

        diagnostic.add_step("Perfil completo", True, "OK")
        return profile_data

    @staticmethod
    def _find_intersection_distances(profile_points, intersect_points):
        if not intersect_points or not profile_points:
            return 0.0, 0.0

        start_d = 0.0
        end_d = profile_points[-1].distance if profile_points else 0.0

        first_pt = intersect_points[0]
        last_pt = intersect_points[-1]

        min_d1 = float("inf")
        min_d2 = float("inf")

        for pp in profile_points:
            d1 = math.sqrt((pp.x - first_pt.x()) ** 2 + (pp.y - first_pt.y()) ** 2)
            d2 = math.sqrt((pp.x - last_pt.x()) ** 2 + (pp.y - last_pt.y()) ** 2)
            if d1 < min_d1:
                min_d1 = d1
                start_d = pp.distance
            if d2 < min_d2:
                min_d2 = d2
                end_d = pp.distance

        return min(start_d, end_d), max(start_d, end_d)

    @staticmethod
    def _assign_horizons_to_points(profile_points, intersected_feature):
        if not intersected_feature.horizons:
            return

        start_d = intersected_feature.intersection_start
        end_d = intersected_feature.intersection_end

        for point in profile_points:
            if start_d <= point.distance <= end_d:
                for horizon in intersected_feature.horizons:
                    # horizon.top / horizon.bottom están en cm.
                    # point.elevation está en metros.
                    # Convertimos profundidad cm a metros para obtener elevación del horizonte.
                    top_m = horizon.top / 100.0
                    bottom_m = horizon.bottom / 100.0
                    h_copy = HorizonData(
                        name=horizon.name,
                        top=point.elevation - bottom_m,
                        bottom=point.elevation - top_m,
                        color=horizon.color,
                        texture=horizon.texture,
                        boundary_type=horizon.boundary_type,
                        folding=horizon.folding,
                        fault_type=horizon.fault_type,
                        fault_displacement=horizon.fault_displacement,
                        image_path=horizon.image_path,
                        inclination=horizon.inclination,
                    )
                    h_copy.depth_top = horizon.top
                    h_copy.depth_bottom = horizon.bottom
                    h_copy.surface_elevation = point.elevation
                    point.horizons.append(h_copy)
