import json
import uuid
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsProject, QgsField
from qgis.PyQt.QtCore import QVariant
from .profile_engine import HorizonData
from .materials import get_material_color, is_material_predefined

import os

# Nombre del campo para el enlace (ID único)
ID_FIELD_NAME = "edafo_id"


class HorizonManager:
    """Clase para gestionar el almacenamiento de perfiles en un archivo JSON externo (sidecar)."""

    @staticmethod
    def get_storage_path(layer):
        """Calcula la ruta del archivo de perfiles basado en la fuente de la capa."""
        if not layer or not layer.source():
            return None

        source_path = layer.source()
        # Si es un shapefile, el source es el .shp
        # Quitamos la extensión y añadimos _profiles.json
        base_path = os.path.splitext(source_path)[0]
        return f"{base_path}_profiles.json"

    @staticmethod
    def _read_all_profiles(layer):
        """Lee el archivo JSON completo de la capa."""
        path = HorizonManager.get_storage_path(layer)
        if not path or not os.path.exists(path):
            return {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error leyendo archivo de perfiles: {e}")
            return {}

    @staticmethod
    def _write_all_profiles(layer, data):
        """Escribe el archivo JSON completo de la capa."""
        path = HorizonManager.get_storage_path(layer)
        if not path:
            return False
        ## try, si hay un error me lo va a mostrar con el print
        ## with open significa abrir el archivo con las siguientes instrucciones
        ## json.dump se usa para guardar los datos en el archivo json

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            print(f"Error escribiendo archivo de perfiles: {e}")
            return False

    ## @staticmethod significa que la funcion se puede usar sin crear un objeto de la clase

    @staticmethod
    def ensure_id_field(layer):
        """Asegura que el campo de ID existe en la capa."""
        if not layer:
            return False

        idx = layer.fields().indexOf(ID_FIELD_NAME)
        if idx == -1:
            field = QgsField(ID_FIELD_NAME, QVariant.String, "Text", 50)
            if not layer.isEditable():
                if not layer.dataProvider().addAttributes([field]):
                    return False
            else:
                if not layer.addAttribute(field):
                    return False
            layer.updateFields()
        return True

    @staticmethod
    def get_feature_id(feature, layer, auto_generate=True):
        """Obtiene o genera un ID único para la entidad."""
        if not feature or not layer:
            return None

        idx = layer.fields().indexOf(ID_FIELD_NAME)
        if idx == -1:
            if not auto_generate:
                return None
            if not HorizonManager.ensure_id_field(layer):
                return None
            idx = layer.fields().indexOf(ID_FIELD_NAME)

        val = feature.attribute(idx)
        if val and str(val).strip() and str(val) != "NULL":
            return str(val).strip()

        if not auto_generate:
            return None

        new_id = str(uuid.uuid4())[:8]

        was_editable = layer.isEditable()
        if not was_editable:
            if not layer.startEditing():
                return None

        layer.changeAttributeValue(feature.id(), idx, new_id)

        if not was_editable:
            layer.commitChanges()
        else:
            layer.triggerRepaint()

        return new_id

    @staticmethod
    def get_profile_data(feature, layer=None):
        """Recuperamos los datos del perfil desde el archivo externo."""
        if feature is None or layer is None:
            return -1, "", []

        e_id = HorizonManager.get_feature_id(feature, layer, auto_generate=False)
        if not e_id:
            return -1, "", []

        all_profiles = HorizonManager._read_all_profiles(layer)
        profile_data = all_profiles.get(e_id)

        if not profile_data:
            return -1, "", []

        try:
            desc = profile_data.get("description", "")
            prof_id = profile_data.get("profile_id", -1)
            horiz = [
                HorizonManager.horizon_from_dict(h)
                for h in profile_data.get("horizontes", [])
            ]
            return prof_id, desc, horiz
        except Exception as e:
            print(f"Error procesando datos del perfil: {e}")
            return -1, "", []

    @staticmethod
    def get_profile_cells(feature, layer=None):
        """Recupera la grilla de celdas (si existe) desde el sidecar del perfil."""
        if feature is None or layer is None:
            return []

        e_id = HorizonManager.get_feature_id(feature, layer, auto_generate=False)
        if not e_id:
            return []

        all_profiles = HorizonManager._read_all_profiles(layer)
        profile_data = all_profiles.get(e_id)
        if not profile_data:
            return []

        try:
            return profile_data.get("cells", []) or []
        except Exception:
            return []

    @staticmethod
    def get_horizons(feature, layer=None):
        """Obtiene solo la lista de horizontes para una entidad."""
        if feature is None:
            return []
        _, _, horizons = HorizonManager.get_profile_data(feature, layer)
        return horizons

    ##_,_, se usa cuando no se necesita una variable al momento de recuperar los datos
    ## por ejemplo en esta linea
    @staticmethod
    def horizon_to_dict(horizon, h_id=None):
        """Serializa un objeto HorizonData a un diccionario JSON."""
        return {
            "id": h_id,
            "name": horizon.name,
            "top": horizon.top,
            "bottom": horizon.bottom,
            "color": horizon.color.name(),
            "texture": horizon.texture,
            "boundary_type": horizon.boundary_type,
            "folding": horizon.folding,
            "fault_type": horizon.fault_type,
            "fault_displacement": horizon.fault_displacement,
            "image_path": horizon.image_path,
            "inclination": getattr(horizon, "inclination", 0),
        }

    @staticmethod
    def horizon_from_dict(data):
        """Reconstruye un objeto HorizonData desde un diccionario."""
        return HorizonData(
            name=data.get("name", "Nuevo Horizonte"),
            top=float(data.get("top", 0)),
            bottom=float(data.get("bottom", 30)),
            color=QColor(data.get("color", "#8b4513")),
            texture=data.get("texture", "Loam"),
            boundary_type=data.get("boundary_type", "abrupt"),
            folding=data.get("folding", 0),
            fault_type=data.get("fault_type", "none"),
            fault_displacement=data.get("fault_displacement", 0),
            image_path=data.get(
                "image_path", data.get("png_path", data.get("svg_path", None))
            ),
            inclination=data.get("inclination", 0),
        )

    @staticmethod
    def save_profile_data(
        feature, layer, profile_id, description, horizontes, cells=None
    ):
        """Guardar los datos del perfil en el archivo externo vinculado por ID."""
        if feature is None or layer is None:
            return False

        e_id = HorizonManager.get_feature_id(feature, layer)
        if not e_id:
            return False

        # Cargar perfiles existentes
        all_profiles = HorizonManager._read_all_profiles(layer)

        # Preparar nuevos datos
        horizons_data = [
            HorizonManager.horizon_to_dict(h, h_id=i + 1)
            for i, h in enumerate(horizontes)
        ]

        try:
            p_id = int(profile_id)
        except (ValueError, TypeError):
            p_id = profile_id if profile_id else -1

        profile_cells = (
            cells if cells is not None else all_profiles.get(e_id, {}).get("cells", [])
        )

        all_profiles[e_id] = {
            "profile_id": p_id,
            "description": description if description else "",
            "horizontes": horizons_data,
            "cells": profile_cells,
            "fid_original": feature.id(),  # Referencia útil para el usuario
        }

        # Guardar todo al archivo
        return HorizonManager._write_all_profiles(layer, all_profiles)

    @staticmethod
    def add_horizon(feature, layer, horizon):
        profile_id, description, horizons = HorizonManager.get_profile_data(
            feature, layer
        )
        horizons.append(horizon)
        HorizonManager.save_profile_data(
            feature, layer, profile_id, description, horizons
        )

    @staticmethod
    def update_horizon(feature, layer, index, new_horizon):
        profile_id, description, horizons = HorizonManager.get_profile_data(
            feature, layer
        )
        if 0 <= index < len(horizons):
            horizons[index] = new_horizon
            HorizonManager.save_profile_data(
                feature, layer, profile_id, description, horizons
            )

    @staticmethod
    def remove_horizon(feature, layer, index):
        profile_id, description, horizons = HorizonManager.get_profile_data(
            feature, layer
        )
        if 0 <= index < len(horizons):
            horizons.pop(index)
            HorizonManager.save_profile_data(
                feature, layer, profile_id, description, horizons
            )

    @staticmethod
    def clear_horizons(feature, layer):
        profile_id, description, _ = HorizonManager.get_profile_data(feature, layer)
        HorizonManager.save_profile_data(feature, layer, profile_id, description, [])

    @staticmethod
    def get_horizon_at_depth(feature, depth, layer=None):
        horizons = HorizonManager.get_horizons(feature, layer)
        for horizon in horizons:
            if horizon.top <= depth < horizon.bottom:
                return horizon
        return None

    @staticmethod
    def rechain_horizons(horizons):
        if not horizons:
            return []

        current_top = 0  # Siempre empezar desde 0 para que el primer horizonte comience en superficie
        for h in horizons:
            thickness = h.bottom - h.top
            h.top = current_top
            h.bottom = current_top + thickness
            current_top = h.bottom
        return horizons

    @staticmethod
    def validate_horizons(horizons):
        if len(horizons) < 2:
            return True, ""

        for i in range(len(horizons) - 1):
            curr = horizons[i]
            nxt = horizons[i + 1]
            if abs(curr.bottom - nxt.top) > 0.01:
                return (
                    False,
                    f"Existe un solapamiento o hueco entre '{curr.name}' y '{nxt.name}'.",
                )

        return True, ""

    @staticmethod
    def save_layer_profile(layer, horizons):
        if layer is None:
            return False

        horizons_data = [HorizonManager.horizon_to_dict(h) for h in horizons]
        horizons_json = json.dumps(horizons_data, ensure_ascii=False)

        layer.setCustomProperty("edafo_profile_template", horizons_json)
        return True

    @staticmethod
    def get_layer_profile(layer):
        if layer is None:
            return []

        horizons_json = layer.customProperty("edafo_profile_template")
        if not horizons_json:
            return []

        try:
            horizons_data = json.loads(horizons_json)
            if isinstance(horizons_data, list):
                return [HorizonManager.horizon_from_dict(h) for h in horizons_data]
        except (json.JSONDecodeError, TypeError):
            pass

        return []
