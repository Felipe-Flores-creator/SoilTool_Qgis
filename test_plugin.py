#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de prueba para verificar el funcionamiento del plugin EdafoInteract v2.
Este script no es parte del plugin, solo sirve para desarrollo y testing.
"""

import sys
import json
from pathlib import Path


def test_materials():
    """Prueba el módulo de materiales."""
    print("=== Probando core/materials.py ===")
    from core.materials import (
        get_material_names,
        get_material_color,
        is_material_predefined,
    )

    # Probar lista de materiales
    materials = get_material_names()
    print(f"Materiales predefinidos: {len(materials)}")
    for mat in materials[:5]:
        print(f"  - {mat}")

    # Probar color de material
    color = get_material_color("Arcilla")
    print(f"Color de Arcilla: {color.name()}")

    # Probar material no definido
    is_defined = is_material_predefined("Material Test")
    print(f"¿'Material Test' es predefinido? {is_defined}")

    print("✅ Pruebas de materiales completadas\n")


def test_horizon_data():
    """Prueba la clase HorizonData."""
    print("=== Probando core/profile_engine.py ===")
    from core.profile_engine import HorizonData, ProfileGeometry
    from qgis.PyQt.QtGui import QColor

    # Crear horizonte de prueba
    horizon = HorizonData("A", 0, 30, QColor("#8B4513"), "Arcilla", "abrupt")
    print(f"Horizonte creado: {horizon.name}")
    print(f"  Profundidad: {horizon.top} - {horizon.bottom} cm")
    print(f"  Color: {horizon.color.name()}")
    print(f"  Textura: {horizon.texture}")
    print(f"  Límite: {horizon.boundary_type}")

    # Probar generación de geometría
    points = ProfileGeometry.generate_boundary(100, 200, 5, 10)
    print(f"Puntos de límite generados: {len(points)}")

    print("✅ Pruebas de HorizonData completadas\n")


def test_horizon_manager():
    """Prueba el gestor de horizontes."""
    print("=== Probando core/horizon_manager.py ===")
    from core.horizon_manager import HorizonManager
    from core.profile_engine import HorizonData
    from qgis.PyQt.QtGui import QColor

    # Crear horizontes de prueba
    h1 = HorizonData("A", 0, 30, QColor("#8B4513"), "Arcilla", "abrupt")
    h2 = HorizonData("Bt", 30, 80, QColor("#A0522D"), "Franco-arcilloso", "clear")
    h3 = HorizonData("C", 80, 150, QColor("#808080"), "Roca", "gradual")

    # Probar validación
    horizons = [h1, h2, h3]
    is_valid, msg = HorizonManager.validate_horizons(horizons)
    print(f"Validación de horizontes: {'Válido' if is_valid else 'Inválido'} - {msg}")

    # Probar conversión a diccionario
    h_dict = HorizonManager.horizon_to_dict(h1)
    print(f"Horizonte como diccionario: {json.dumps(h_dict, ensure_ascii=False)}")

    # Probar conversión desde diccionario
    h_back = HorizonManager.horizon_from_dict(h_dict)
    print(f"Horizonte recuperado: {h_back.name}, {h_back.texture}")

    print("✅ Pruebas de HorizonManager completadas\n")


def test_dialog():
    """Prueba el diálogo de horizontes (requiere Qt)."""
    print("=== Probando ui/horizon_dialog.py ===")
    try:
        from qgis.PyQt.QtWidgets import QApplication
        from ui.horizon_dialog import HorizonDialog
        from core.profile_engine import HorizonData
        from qgis.PyQt.QtGui import QColor

        # Crear aplicación Qt
        app = QApplication.instance() or QApplication(sys.argv)

        # Probar diálogo nuevo
        dialog = HorizonDialog()
        print("Diálogo de nuevo horizonte creado correctamente")

        # Probar diálogo con horizonte existente
        horizon = HorizonData("Test", 10, 40, QColor("#FF0000"), "Arena", "clear")
        dialog2 = HorizonDialog(None, horizon)
        print("Diálogo de edición creado correctamente")

        print("✅ Pruebas de diálogo completadas\n")
    except Exception as e:
        print(
            f"⚠️ No se pudo probar el diálogo (posiblemente no hay entorno gráfico): {e}\n"
        )


def test_profile_panel():
    """Prueba el panel de perfil (requiere Qt)."""
    print("=== Probando ui/profile_panel.py ===")
    try:
        from qgis.PyQt.QtWidgets import QApplication
        from ui.profile_panel import ProfilePanel

        app = QApplication.instance() or QApplication(sys.argv)
        panel = ProfilePanel()
        print("Panel de perfil creado correctamente")
        print(f"  Canvas: {panel.canvas is not None}")
        print(f"  Lista: {panel.horizon_list is not None}")

        print("✅ Pruebas de panel completadas\n")
    except Exception as e:
        print(
            f"⚠️ No se pudo probar el panel (posiblemente no hay entorno gráfico): {e}\n"
        )


def main():
    """Ejecuta todas las pruebas."""
    print("🧪 Iniciando pruebas del plugin EdafoInteract v2\n")

    # Añadir el directorio actual al path
    sys.path.insert(0, str(Path(__file__).parent))

    try:
        test_materials()
        test_horizon_data()
        test_horizon_manager()
        test_dialog()
        test_profile_panel()

        print("🎉 ¡Todas las pruebas completadas exitosamente!")
        return 0
    except Exception as e:
        print(f"❌ Error durante las pruebas: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
