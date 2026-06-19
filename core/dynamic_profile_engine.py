# -*- coding: utf-8 -*-
"""
Motor de perfil topográfico dinámico.
Realiza muestreo a paso constante sobre un DEM e intersecta espacialmente
con polígonos edafológicos en tiempo de ejecución, normalizando CRS.

Versión optimizada con:
- Caché de horizontes por feature ID (evita I/O repetitivo)
- SpatialIndex para búsqueda rápida de polígonos
- sample_dem simplificado (solo método sample, el más rápido)
- Skip de horizontes si el feature repite
"""

import math
import numpy as np
from qgis.core import (
    QgsProject,
    QgsPointXY,
    QgsGeometry,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsRasterDataProvider,
    QgsFeatureRequest,
    QgsRectangle,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsSpatialIndex,
)
from .horizon_manager import HorizonManager


class DynamicProfileEngine:
    """Motor para generar perfiles de elevación y estratigrafía edafológica."""

    @staticmethod
    def sample_dem(dem_layer, point):
        """Muestrea el DEM (solo método sample, el más rápido)."""
        if not dem_layer or not dem_layer.isValid():
            return None
        provider = dem_layer.dataProvider()
        if not provider:
            return None
        try:
            val, success = provider.sample(point, 1)
            if success and val is not None and not np.isnan(val) and np.isfinite(val):
                return float(val)
        except Exception:
            pass
        return None

    @staticmethod
    def _build_horizons_cache(soils_layer):
        """
        Construye un caché {feature_id: (poly_id, [horizons])} para TODAS las
        features de la capa de suelos. Esto evita leer el JSON sidecar para
        cada punto muestreado.
        """
        cache = {}
        if not soils_layer or not soils_layer.isValid():
            return cache
        for feature in soils_layer.getFeatures():
            fid = feature.id()
            try:
                poly_id = HorizonManager.get_feature_id(
                    feature, soils_layer, auto_generate=False
                )
                horizons = HorizonManager.get_horizons(feature, soils_layer)
                cache[fid] = (poly_id, horizons)
            except Exception:
                cache[fid] = (None, [])
        return cache

    @staticmethod
    def find_soil_feature_fast(soils_layer, point_soils, spatial_index=None):
        """
        Encuentra la entidad edafológica usando QgsSpatialIndex para
        búsqueda ultra rápida. Si no hay índice, se construye uno.
        """
        if not soils_layer or not soils_layer.isValid():
            return None

        # Construir o reusar índice espacial
        if spatial_index is None:
            spatial_index = QgsSpatialIndex(soils_layer.getFeatures())

        # Buscar los features más cercanos al punto (buffer mucho menor ~0.00001 grados ~1m)
        pt_geom = QgsGeometry.fromPointXY(point_soils)
        nearest_ids = spatial_index.nearestNeighbor(point_soils, 5)  # top 5 candidatos

        for fid in nearest_ids:
            try:
                feature = soils_layer.getFeature(fid)
                if not feature:
                    continue
                geom = feature.geometry()
                if geom and (geom.contains(pt_geom) or geom.intersects(pt_geom)):
                    return feature
            except Exception:
                continue

        # Fallback: si falla el índice, usar el método original con buffer grande
        rect = QgsRectangle(
            point_soils.x() - 0.0001,
            point_soils.y() - 0.0001,
            point_soils.x() + 0.0001,
            point_soils.y() + 0.0001,
        )
        request = QgsFeatureRequest().setFilterRect(rect)
        for feature in soils_layer.getFeatures(request):
            geom = feature.geometry()
            if geom and (geom.contains(pt_geom) or geom.intersects(pt_geom)):
                return feature
        return None

    @staticmethod
    def generate_dynamic_profile(
        dem_layer, soils_layer, line_geometry, step_size=5.0, map_crs=None
    ):
        """
        Genera una lista de diccionarios de puntos muestreados a paso constante.
        Versión optimizada con caché y SpatialIndex.
        """
        if not line_geometry or line_geometry.isEmpty():
            return []

        total_length = line_geometry.length()
        if total_length <= 0:
            return []

        if map_crs is None:
            map_crs = QgsProject.instance().crs()

        # Configurar transformaciones de CRS
        dem_crs = dem_layer.crs() if dem_layer else map_crs
        soils_crs = soils_layer.crs() if soils_layer else map_crs

        transform_to_dem = None
        if dem_layer and dem_crs != map_crs:
            try:
                transform_to_dem = QgsCoordinateTransform(
                    map_crs, dem_crs, QgsProject.instance()
                )
            except Exception:
                transform_to_dem = None

        transform_to_soils = None
        if soils_layer and soils_crs != map_crs:
            try:
                transform_to_soils = QgsCoordinateTransform(
                    map_crs, soils_crs, QgsProject.instance()
                )
            except Exception:
                transform_to_soils = None

        # --- OPTIMIZACIÓN: Caché de horizontes + SpatialIndex ---
        horizons_cache = {}
        spatial_index = None
        last_feat_id = None  # Para evitar buscar repetido en puntos consecutivos

        if soils_layer:
            # Construir SpatialIndex UNA SOLA VEZ
            try:
                spatial_index = QgsSpatialIndex(soils_layer.getFeatures())
            except Exception:
                spatial_index = None

        points_data = []
        distance = 0.0

        # Muestreo a intervalo regular
        while distance <= total_length:
            # Interpolar punto en el mapa
            pt_geom = line_geometry.interpolate(distance)
            if pt_geom.isEmpty():
                distance += step_size
                continue

            map_pt = pt_geom.asPoint()

            # Obtener Z (DEM) - solo sample, sin identify fallback
            z = None
            if dem_layer:
                try:
                    pt_dem = (
                        transform_to_dem.transform(map_pt)
                        if transform_to_dem
                        else map_pt
                    )
                except Exception:
                    pt_dem = map_pt
                z = DynamicProfileEngine.sample_dem(dem_layer, pt_dem)

            # Obtener Polígono de Suelo y Horizontes
            poly_id = None
            horizons = []
            if soils_layer:
                try:
                    pt_soils = (
                        transform_to_soils.transform(map_pt)
                        if transform_to_soils
                        else map_pt
                    )
                except Exception:
                    pt_soils = map_pt

                # Búsqueda rápida: si estamos en el mismo feature que el punto anterior, reusar
                # (los puntos consecutivos suelen caer en el mismo polígono)
                feat = None
                if last_feat_id is not None:
                    # Verificar si el punto anterior aún es válido (optimización común)
                    try:
                        prev_feat = soils_layer.getFeature(last_feat_id)
                        if prev_feat:
                            prev_geom = prev_feat.geometry()
                            pt_g = QgsGeometry.fromPointXY(pt_soils)
                            if prev_geom and prev_geom.contains(pt_g):
                                feat = prev_feat
                    except Exception:
                        pass

                if feat is None:
                    feat = DynamicProfileEngine.find_soil_feature_fast(
                        soils_layer, pt_soils, spatial_index
                    )

                if feat:
                    last_feat_id = feat.id()
                    # Usar caché de horizontes para evitar leer JSON repetidamente
                    if last_feat_id in horizons_cache:
                        poly_id, horizons = horizons_cache[last_feat_id]
                    else:
                        poly_id = HorizonManager.get_feature_id(
                            feat, soils_layer, auto_generate=False
                        )
                        horizons = HorizonManager.get_horizons(feat, soils_layer)
                        horizons_cache[last_feat_id] = (poly_id, horizons)
                else:
                    last_feat_id = None

            points_data.append(
                {
                    "distance": distance,
                    "x": map_pt.x(),
                    "y": map_pt.y(),
                    "z": z if z is not None else 0.0,
                    "poly_id": poly_id,
                    "horizons": horizons,
                }
            )

            # Si estamos al final del perfil, terminar
            if distance == total_length:
                break

            distance += step_size
            if distance > total_length:
                distance = total_length

        return points_data
