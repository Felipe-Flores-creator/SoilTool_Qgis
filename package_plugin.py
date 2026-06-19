import os
import zipfile
import shutil

def package_plugin():
    # Configuración
    plugin_name = "SoilTool"  # Nombre de la carpeta dentro del ZIP
    output_filename = "SoilTool.zip"
    
    # Archivos y carpetas a incluir
    include_paths = [
        "core",
        "resources",
        "ui",
        "__init__.py",
        "edafo_interact.py",
        "metadata.txt",
        "README.md",
        "LICENSE"
    ]
    
    # Extensiones a ignorar
    ignore_extensions = [".pyc", ".pyo", ".git", ".ipynb", ".bak"]
    ignore_dirs = ["__pycache__", ".git", ".vscode", ".idea"]

    print(f"--- Iniciando empaquetado de {plugin_name} ---")

    # Limpiar si ya existe el zip previo
    if os.path.exists(output_filename):
        os.remove(output_filename)
        print(f"Eliminado archivo previo: {output_filename}")

    try:
        with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for path in include_paths:
                if not os.path.exists(path):
                    print(f"ADVERTENCIA: No se encontró {path}, saltando...")
                    continue

                if os.path.isfile(path):
                    # Añadir archivo individual
                    zip_path = os.path.join(plugin_name, path)
                    zipf.write(path, zip_path)
                    print(f"Añadido archivo: {path}")
                
                elif os.path.isdir(path):
                    # Recorrer directorio
                    for root, dirs, files in os.walk(path):
                        # Filtrar directorios ignorados
                        dirs[:] = [d for d in dirs if d not in ignore_dirs]
                        
                        for file in files:
                            if any(file.endswith(ext) for ext in ignore_extensions):
                                continue
                            
                            file_path = os.path.join(root, file)
                            # Calcular la ruta relativa dentro del ZIP
                            # Queremos que empiece con plugin_name/
                            arcname = os.path.join(plugin_name, file_path)
                            zipf.write(file_path, arcname)
                    print(f"Añadido directorio: {path}")

        print(f"\n--- ¡Éxito! ---")
        print(f"Archivo creado: {os.path.abspath(output_filename)}")
        print(f"Tamaño: {os.path.getsize(output_filename) / 1024:.2f} KB")
        print("Este archivo está listo para ser subido al repositorio de QGIS.")

    except Exception as e:
        print(f"ERROR durante el empaquetado: {e}")

if __name__ == "__main__":
    package_plugin()
