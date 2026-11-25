# -*- coding: utf-8 -*-
"""
Motor de perfil topográfico dinámico.
Realiza muestreo a paso constante sobre un DEM e intersecta espacialmente
con polígonos edafológicos en tiempo de ejecución, normalizando CRS.

- Distancias en metros reales (también si el mapa está en grados).
- Muestreo bilineal del DEM leyendo una sola vez el bloque que cubre la línea
  (rápido y sin el efecto 'escalera' del vecino más cercano).
- Sin dato (NoData) -> NaN: el gráfico muestra un vacío en lugar de caer a 0.
- Caché de horizontes por entidad y SpatialIndex para los polígonos.
"""

import math

import numpy as np
from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProject,
    QgsRectangle,
    QgsSpatialIndex,
    QgsUnitTypes,
)

from .horizon_manager import HorizonManager

MAX_BLOCK_CELLS = 16_000_000  # por encima de esto se usa provider.sample()

_NUMPY_TYPES = {
    "Byte": np.uint8,
    "UInt16": np.uint16,
    "Int16": np.int16,
    "UInt32": np.uint32,
    "Int32": np.int32,
    "Float32": np.float32,
    "Float64": np.float64,
    "Int8": np.int8,
}


class _DemSampler:
    """Muestreo bilineal de la banda 1 de un DEM dentro de una ventana."""

    def __init__(self, dem_layer, extent_dem_crs):
        self.layer = dem_layer
        self.provider = dem_layer.dataProvider()
        self.grid = None
        try:
            self._read_block(extent_dem_crs)
        except Exception:
            self.grid = None

    def _read_block(self, ext):
        lyr_ext = self.layer.extent()
        rx = self.layer.rasterUnitsPerPixelX()
        ry = self.layer.rasterUnitsPerPixelY()
        if rx <= 0 or ry <= 0:
            return
        # Ventana alineada a la grilla del raster, con margen de 2 celdas
        c0 = max(0, int(math.floor((ext.xMinimum() - lyr_ext.xMinimum()) / rx)) - 2)
        c1 = min(
            self.layer.width(),
            int(math.ceil((ext.xMaximum() - lyr_ext.xMinimum()) / rx)) + 2,
        )
        r0 = max(0, int(math.floor((lyr_ext.yMaximum() - ext.yMaximum()) / ry)) - 2)
        r1 = min(
            self.layer.height(),
            int(math.ceil((lyr_ext.yMaximum() - ext.yMinimum()) / ry)) + 2,
        )
        w, h = c1 - c0, r1 - r0
        if w <= 1 or h <= 1 or w * h > MAX_BLOCK_CELLS:
            return
        win = QgsRectangle(
            lyr_ext.xMinimum() + c0 * rx,
            lyr_ext.yMaximum() - r1 * ry,
            lyr_ext.xMinimum() + c1 * rx,
            lyr_ext.yMaximum() - r0 * ry,
        )
        block = self.provider.block(1, win, w, h)
        if not block or not block.isValid():
            return
        dtype = _NUMPY_TYPES.get(_type_name(block.dataType()))
        if dtype is None:
            return
        raw = bytes(block.data())
        arr = np.frombuffer(raw, dtype=dtype)
        if arr.size != w * h:
            return
        grid = arr.reshape((h, w)).astype(np.float64)
        if self.provider.sourceHasNoDataValue(1) and self.provider.useSourceNoDataValue(
            1
        ):
            nd = self.provider.sourceNoDataValue(1)
            grid[grid == nd] = np.nan
        grid[~np.isfinite(grid)] = np.nan
        self.grid = grid
        self.x0 = win.xMinimum()
        self.y0 = win.yMaximum()
        self.rx, self.ry = rx, ry

    def sample(self, pt):
        if self.grid is None:
            return _sample_provider(self.provider, pt)
        # Coordenadas de celda (centros en .5)
        fx = (pt.x() - self.x0) / self.rx - 0.5
        fy = (self.y0 - pt.y()) / self.ry - 0.5
        h, w = self.grid.shape
        if fx < -0.5 or fy < -0.5 or fx > w - 0.5 or fy > h - 0.5:
            return _sample_provider(self.provider, pt)
        fx = min(max(fx, 0.0), w - 1.0)
        fy = min(max(fy, 0.0), h - 1.0)
        c, r = int(fx), int(fy)
        c1, r1 = min(c + 1, w - 1), min(r + 1, h - 1)
        tx, ty = fx - c, fy - r
        q = self.grid
        vals = (q[r, c], q[r, c1], q[r1, c], q[r1, c1])
        weights = ((1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty)
        num = sum(v * wt for v, wt in zip(vals, weights) if not np.isnan(v))
        den = sum(wt for v, wt in zip(vals, weights) if not np.isnan(v))
        if den < 0.25:  # mayoría de vecinos sin dato
            return None
        return float(num / den)


def _type_name(dt):
    name = getattr(dt, "name", None)
    if name:
        return name
    for n in _NUMPY_TYPES:
        if dt == getattr(Qgis.DataType, n, None) or dt == getattr(Qgis, n, None):
            return n
    return ""


def _sample_provider(provider, pt):
    """provider.sample() descartando NoData y puntos fuera del raster."""
    try:
        if not provider.extent().contains(pt):
            return None
        val, ok = provider.sample(pt, 1)
        if not ok or val is None or not np.isfinite(val):
            return None
        if provider.sourceHasNoDataValue(1) and val == provider.sourceNoDataValue(1):
            return None
        return float(val)
    except Exception:
        return None


class DynamicProfileEngine:
    """Motor para generar perfiles de elevación y estratigrafía edafológica."""

    @staticmethod
    def sample_dem(dem_layer, point):
        """Muestrea el DEM en un punto (vecino más cercano)."""
        if not dem_layer or not dem_layer.isValid():
            return None
        provider = dem_layer.dataProvider()
        if not provider:
            return None
        return _sample_provider(provider, point)

    @staticmethod
    def line_length_m(line_geometry, crs):
        """Longitud de la línea en metros (elipsoidal si el CRS es geográfico)."""
        if crs is not None and crs.isValid() and crs.isGeographic():
            project = QgsProject.instance()
            ellipsoid = project.ellipsoid()
            if not ellipsoid or ellipsoid.upper() == "NONE":
                ellipsoid = "EPSG:7030"  # WGS84
            da = QgsDistanceArea()
            da.setSourceCrs(crs, project.transformContext())
            da.setEllipsoid(ellipsoid)
            length = da.measureLength(line_geometry)
            if length > 0 and da.willUseEllipsoid():
                return length
            # Respaldo: aproximación esférica por segmentos (haversine)
            pts = line_geometry.asPolyline() or [
                p for part in line_geometry.asMultiPolyline() for p in part
            ]
            total = 0.0
            for p1, p2 in zip(pts[:-1], pts[1:]):
                la1, la2 = math.radians(p1.y()), math.radians(p2.y())
                dla, dlo = la2 - la1, math.radians(p2.x() - p1.x())
                h = (
                    math.sin(dla / 2) ** 2
                    + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
                )
                total += 2 * 6371008.8 * math.asin(min(1.0, math.sqrt(h)))
            return total
        factor = 1.0
        if crs is not None and crs.isValid():
            try:
                meters = getattr(Qgis, "DistanceUnit", None)
                meters = meters.Meters if meters else QgsUnitTypes.DistanceMeters
                factor = QgsUnitTypes.fromUnitToUnitFactor(crs.mapUnits(), meters)
            except Exception:
                factor = 1.0
        return line_geometry.length() * factor

    @staticmethod
    def find_soil_feature_fast(soils_layer, point_soils, spatial_index=None):
        """Encuentra la entidad edafológica que contiene el punto."""
        if not soils_layer or not soils_layer.isValid():
            return None
        if spatial_index is None:
            spatial_index = QgsSpatialIndex(soils_layer.getFeatures())

        pt_geom = QgsGeometry.fromPointXY(point_soils)
        rect = QgsRectangle(
            point_soils.x(), point_soils.y(), point_soils.x(), point_soils.y()
        )
        for fid in spatial_index.intersects(rect):
            try:
                feature = soils_layer.getFeature(fid)
                geom = feature.geometry()
                if geom and geom.intersects(pt_geom):
                    return feature
            except Exception:
                continue

        # Respaldo sin índice
        request = QgsFeatureRequest().setFilterRect(rect)
        for feature in soils_layer.getFeatures(request):
            geom = feature.geometry()
            if geom and geom.intersects(pt_geom):
                return feature
        return None

    @staticmethod
    def generate_dynamic_profile(
        dem_layer, soils_layer, line_geometry, step_size=5.0, map_crs=None
    ):
        """
        Muestrea la línea cada step_size metros.

        Devuelve una lista de dicts con:
            distance (m desde el inicio), frac (0-1 a lo largo de la línea),
            x, y (CRS del mapa), z (m o NaN), poly_id, unit (rótulo del perfil),
            fid, horizons.
        """
        if not line_geometry or line_geometry.isEmpty():
            return []
        if map_crs is None:
            map_crs = QgsProject.instance().crs()

        length_crs = line_geometry.length()
        length_m = DynamicProfileEngine.line_length_m(line_geometry, map_crs)
        if length_crs <= 0 or length_m <= 0:
            return []

        step = max(float(step_size), length_m / 20000.0)  # máx. ~20 000 muestras
        n = max(2, int(math.ceil(length_m / step)))

        project = QgsProject.instance()
        transform_to_dem = None
        sampler = None
        if dem_layer and dem_layer.isValid():
            if dem_layer.crs() != map_crs:
                try:
                    transform_to_dem = QgsCoordinateTransform(
                        map_crs, dem_layer.crs(), project
                    )
                except Exception:
                    transform_to_dem = None
            try:
                bbox = line_geometry.boundingBox()
                if transform_to_dem:
                    bbox = transform_to_dem.transformBoundingBox(bbox)
                sampler = _DemSampler(dem_layer, bbox)
            except Exception:
                sampler = None

        transform_to_soils = None
        spatial_index = None
        if soils_layer and soils_layer.isValid():
            if soils_layer.crs() != map_crs:
                try:
                    transform_to_soils = QgsCoordinateTransform(
                        map_crs, soils_layer.crs(), project
                    )
                except Exception:
                    transform_to_soils = None
            try:
                spatial_index = QgsSpatialIndex(soils_layer.getFeatures())
            except Exception:
                spatial_index = None

        cache = {}
        last_feat = None
        points_data = []
        for i in range(n + 1):
            frac = i / n
            map_pt = line_geometry.interpolate(frac * length_crs).asPoint()

            z = None
            if sampler is not None:
                try:
                    pt_dem = (
                        transform_to_dem.transform(map_pt)
                        if transform_to_dem
                        else map_pt
                    )
                    z = sampler.sample(pt_dem)
                except Exception:
                    z = None

            poly_id, unit, fid, horizons = None, None, None, []
            if soils_layer and soils_layer.isValid():
                try:
                    pt_soils = (
                        transform_to_soils.transform(map_pt)
                        if transform_to_soils
                        else map_pt
                    )
                except Exception:
                    pt_soils = map_pt
                feat = None
                if last_feat is not None:
                    g = last_feat.geometry()
                    if g and g.intersects(QgsGeometry.fromPointXY(pt_soils)):
                        feat = last_feat
                if feat is None:
                    feat = DynamicProfileEngine.find_soil_feature_fast(
                        soils_layer, pt_soils, spatial_index
                    )
                last_feat = feat
                if feat is not None:
                    fid = feat.id()
                    if fid not in cache:
                        p_id = HorizonManager.get_feature_id(
                            feat, soils_layer, auto_generate=False
                        )
                        pid, _, hs = HorizonManager.get_profile_data(feat, soils_layer)
                        hs = sorted(hs, key=lambda h: h.top)
                        label = str(pid) if pid not in (-1, None, "") else None
                        cache[fid] = (p_id, label, hs)
                    poly_id, unit, horizons = cache[fid]

            points_data.append(
                {
                    "distance": frac * length_m,
                    "frac": frac,
                    "x": map_pt.x(),
                    "y": map_pt.y(),
                    "z": z if z is not None else float("nan"),
                    "poly_id": poly_id,
                    "unit": unit,
                    "fid": fid,
                    "horizons": horizons,
                }
            )
        return points_data
