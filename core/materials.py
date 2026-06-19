# -*- coding: utf-8 -*-
"""
Lista de materiales/tipos de suelo predefinidos y utilidades.
"""

from qgis.PyQt.QtGui import QColor

# Materiales predefinidos con sus colores típicos
PREDEFINED_MATERIALS = {
    "Arcilla": {
        "color": QColor("#8B4513"),
        "description": "Suelo fino, plástico cuando está húmedo",
    },
    "Arena": {
        "color": QColor("#F4A460"),
        "description": "Partículas gruesas, drenaje rápido",
    },
    "Limo": {
        "color": QColor("#D2B48C"),
        "description": "Partículas medianas, suave al tacto",
    },
    "Franco": {
        "color": QColor("#8B7355"),
        "description": "Mezcla equilibrada de arena, limo y arcilla",
    },
    "Franco-arcilloso": {
        "color": QColor("#A0522D"),
        "description": "Mezcla con predominancia de arcilla",
    },
    "Franco-arenoso": {
        "color": QColor("#CD853F"),
        "description": "Mezcla con predominancia de arena",
    },
    "Arcilla arenosa": {
        "color": QColor("#8B6914"),
        "description": "Arcilla con alta proporción de arena",
    },
    "Limo arcilloso": {
        "color": QColor("#996515"),
        "description": "Mezcla de limo y arcilla",
    },
    "Grava": {
        "color": QColor("#A9A9A9"),
        "description": "Fragmentos de roca de 2-75 mm",
    },
    "Roca": {"color": QColor("#808080"), "description": "Material rocoso consolidado"},
    "Materia orgánica": {
        "color": QColor("#3D2B1F"),
        "description": "Alto contenido de materia orgánica descompuesta",
    },
    "Turba": {
        "color": QColor("#2F1B14"),
        "description": "Materia orgánica parcialmente descompuesta",
    },
    "Caliza": {
        "color": QColor("#D3D3D3"),
        "description": "Roca sedimentaria compuesta por carbonatos",
    },
    "Yeso": {
        "color": QColor("#F5F5F5"),
        "description": "Mineral de sulfato cálcico hidratado",
    },
    "Ceniza Volcánica": {
        "color": QColor("#696969"),
        "description": "Fragmentos finos de roca volcánica",
    },
    "Esquisto": {
        "color": QColor("#4F4F4F"),
        "description": "Roca metamórfica laminada",
    },
    "Carbón": {
        "color": QColor("#1A1A1A"),
        "description": "Roca sedimentaria rica en carbono",
    },
    "Sal": {
        "color": QColor("#FFFFFF"),
        "description": "Depósitos de evaporitas",
    },
}


def get_material_names():
    """Retorna la lista de nombres de materiales predefinidos."""
    return list(PREDEFINED_MATERIALS.keys())


def get_material_color(material_name):
    """Retorna el color asociado a un material predefinido."""
    if material_name in PREDEFINED_MATERIALS:
        return PREDEFINED_MATERIALS[material_name]["color"]
    # Color por defecto para materiales personalizados
    return QColor("#808080")


def is_material_predefined(material_name):
    """Verifica si un material está en la lista predefinida."""
    return material_name in PREDEFINED_MATERIALS
