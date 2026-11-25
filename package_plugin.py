# -*- coding: utf-8 -*-
"""
Empaqueta SoilTool para el repositorio oficial de QGIS (plugins.qgis.org).

Estructura de carpetas:
    SoilTool_Projects/
    ├── SoilTool/        <- repositorio de GitHub (código fuente, este script)
    └── SoilTool_QGIS/   <- salida para QGIS (generada, fuera de git)
        ├── SoilTool/            copia limpia del plugin (lista para instalar)
        └── SoilTool_X.Y.Z.zip   archivo para subir a plugins.qgis.org

Uso:
    python package_plugin.py
"""

import configparser
import os
import shutil
import sys
import zipfile

PLUGIN_NAME = "SoilTool"  # Debe coincidir con la carpeta raíz dentro del ZIP

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(os.path.dirname(SRC_DIR), "SoilTool_QGIS")

# Sólo esto se envía a QGIS; todo lo demás (README_eng, tests, .git, .venv...)
# se queda únicamente en GitHub.
INCLUDE = [
    "__init__.py",
    "edafo_interact.py",
    "metadata.txt",
    "LICENSE",
    "README.md",
    "core",
    "ui",
    "resources",
]

IGNORE_DIRS = {"__pycache__", ".git", ".venv", "venv", ".vscode", ".idea", "__MACOSX"}
IGNORE_EXT = (".pyc", ".pyo", ".bak", ".zip", ".ipynb", ".log")

REQUIRED_METADATA = [
    "name",
    "description",
    "about",
    "version",
    "qgisMinimumVersion",
    "author",
    "email",
    "repository",
]


def read_metadata():
    cp = configparser.ConfigParser()
    cp.read(os.path.join(SRC_DIR, "metadata.txt"), encoding="utf-8")
    meta = cp["general"]
    missing = [k for k in REQUIRED_METADATA if not meta.get(k)]
    if missing:
        sys.exit(f"ERROR: faltan campos en metadata.txt: {', '.join(missing)}")
    return meta


def ignored(name):
    return name.startswith(".") or name in IGNORE_DIRS or name.endswith(IGNORE_EXT)


def copy_clean(dest):
    """Copia sólo los archivos del plugin a dest (se recrea desde cero)."""
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    for item in INCLUDE:
        src = os.path.join(SRC_DIR, item)
        if not os.path.exists(src):
            sys.exit(f"ERROR: no se encontró {item}")
        if os.path.isdir(src):
            shutil.copytree(
                src,
                os.path.join(dest, item),
                ignore=lambda d, names: [n for n in names if ignored(n)],
            )
        else:
            shutil.copy2(src, os.path.join(dest, item))


def make_zip(folder, zip_path):
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(folder):
            for f in sorted(files):
                full = os.path.join(root, f)
                arc = os.path.join(PLUGIN_NAME, os.path.relpath(full, folder))
                zf.write(full, arc.replace("\\", "/"))


def validate_zip(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    problems = [
        n
        for n in names
        if not n.startswith(PLUGIN_NAME + "/")
        or any(part.startswith(".") or part in IGNORE_DIRS for part in n.split("/"))
        or n.endswith((".pyc", ".pyo"))
    ]
    for required in ("__init__.py", "metadata.txt", "LICENSE"):
        if f"{PLUGIN_NAME}/{required}" not in names:
            problems.append(f"falta {required}")
    if problems:
        sys.exit("ERROR: el ZIP no es válido para QGIS:\n  " + "\n  ".join(problems))
    return len(names)


def main():
    meta = read_metadata()
    version = meta["version"]
    print(f"--- Empaquetando {PLUGIN_NAME} v{version} ---")

    os.makedirs(OUT_DIR, exist_ok=True)
    plugin_dir = os.path.join(OUT_DIR, PLUGIN_NAME)
    zip_path = os.path.join(OUT_DIR, f"{PLUGIN_NAME}_{version}.zip")

    copy_clean(plugin_dir)
    make_zip(plugin_dir, zip_path)
    n = validate_zip(zip_path)

    print(f"Carpeta limpia : {plugin_dir}")
    print(
        f"ZIP para QGIS  : {zip_path} ({n} archivos, "
        f"{os.path.getsize(zip_path) / 1024:.1f} KB)"
    )
    print("Listo para subir a https://plugins.qgis.org/plugins/add/")


if __name__ == "__main__":
    main()
