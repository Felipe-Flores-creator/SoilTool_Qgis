# TODO - Edición manual / preparación de subida a repositorio oficial QGIS

- [x] Actualizar `metadata.txt` a la versión objetivo **1.0.4** (desde 1.0.3 / 1.1.0)
- [x] Actualizar `README.md` (historial) para que refleje **v1.0.4** como actual
- [x] Actualizar `README_eng.md` (historial) para que refleje **v1.0.4** como current
- [ ] Verificar estructura de empaquetado para QGIS Official Repository
  - [ ] Generar ZIP con `python package_plugin.py`
  - [ ] Confirmar que el ZIP incluye `metadata.txt` y `resources/`, `ui/`, `core/` dentro de la carpeta raíz esperada
- [ ] Revisar consistencia de nombre de carpeta dentro del ZIP vs el nombre del plugin en `metadata.txt`
- [ ] Probar instalación del ZIP en QGIS (Manage and Install Plugins → Install from ZIP)
- [ ] Preparar release/tag (si tu flujo oficial lo requiere)

