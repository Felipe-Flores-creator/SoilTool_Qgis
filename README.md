# SoilTool - QGIS Plugin for Soil Profile Visualization

**English Description:**
SoilTool is a scientific QGIS plugin designed for the interactive visualization and management of soil profiles directly within vector layers. It allows users to define, edit, and visualize soil horizons with detailed properties including depth, texture, color, and boundary types. Data is stored efficiently using a sidecar JSON system, ensuring portability and performance.

---

# EdafoInteract v2 - Plugin de QGIS para Visualización de Perfiles de Suelo

Plugin para QGIS que permite la visualización interactiva de perfiles de suelo con gestión completa de horizontes y estratos.

## Características Principales

### 🎯 Funcionalidades Principales

1. **Selección de Features**: Haz clic en cualquier punto o polígono de tus capas vectoriales para visualizar su perfil de suelo asociado.

2. **Gestión Completa de Horizontes**:
   - Añadir nuevos horizontes con profundidades personalizadas
   - Editar horizontes existentes
   - Eliminar horizontes individuales o todos
   - Los datos se guardan automáticamente en los atributos del feature

3. **Tipos de Material Predefinidos**:
   - Arcilla
   - Arena
   - Limo
   - Franco
   - Franco-arcilloso
   - Franco-arenoso
   - Arcilla arenosa
   - Limo arcilloso
   - Grava
   - Roca
   - Materia orgánica
   - Turba

4. **Materiales Personalizados**: Puedes escribir cualquier tipo de material si no está en la lista predefinida.

5. **Visualización Avanzada**:
   - Límites orgánicos entre horizontes
   - Texturas específicas para cada tipo de material
   - Gradientes de color para mayor realismo
   - Tipos de límite: abrupto, claro, gradual, difuso

## 📋 Requisitos

- QGIS 3.0 o superior
- Python 3.x

## 🚀 Instalación

### Método 1: Instalación Manual (Recomendado para desarrollo)

Sigue estos pasos cuidadosamente:

#### Paso 1: Ubicar el directorio de plugins de QGIS

El directorio de plugins varía según tu sistema operativo:

| Sistema Operativo | Ruta del Directorio |
|-------------------|---------------------|
| **Windows** | `C:\Users\[TuUsuario]\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\` |
| **Linux** | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/` |
| **macOS** | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/` |

> **Nota para Windows**: La carpeta `AppData` está oculta por defecto. Para acceder:
> 1. Abre el Explorador de Archivos
> 2. En la barra de direcciones, pega: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
> 3. Presiona Enter

#### Paso 2: Copiar el Plugin

1. Copia la carpeta completa `edafo_interact_v2` (con todos sus archivos y subcarpetas)
2. Pega la carpeta en el directorio de plugins identificado en el Paso 1

#### Paso 3: Activar el Plugin en QGIS

1. **Abre QGIS** (o reinícialo si ya estaba abierto)
2. En el menú superior, haz clic en: **`Complementos`** → **`Gestionar e instalar complementos...`**
3. En la ventana que se abre, selecciona la pestaña **`Instalados`** (lado izquierdo)
4. Busca en la lista: **`Edafo Interact V2`**
5. **Marca la casilla** ✓ al lado del nombre para activarlo
6. Haz clic en **`Aceptar`**

✅ **¡Listo! El plugin está instalado y activo.**

---

### Método 2: Instalación desde ZIP (Si está disponible en el repositorio oficial)

1. En QGIS, ve a: **`Complementos`** → **`Gestionar e instalar complementos...`**
2. Selecciona la pestaña **`Todos`**
3. En la barra de búsqueda, escribe: `Edafo Interact`
4. Selecciona **`Edafo Interact V2`** de la lista
5. Haz clic en el botón **`Instalar complemento`**
6. Espera a que complete la instalación
7. Haz clic en **`Cerrar`**

## 📖 Uso

### Paso 1: Activar la Herramienta

Una vez instalado el plugin, verás un nuevo icono en la barra de herramientas de QGIS:

**Opción A - Desde la barra de herramientas:**
1. Busca el icono 🔍 **"Inspeccionar Perfil"** en la barra de herramientas
2. Haz **clic izquierdo** sobre el icono para activarlo

**Opción B - Desde el menú:**
1. En el menú superior, haz clic en **`Complementos`**
2. En el menú desplegable, selecciona **`EdafoInteract`**
3. Haz clic en **`Inspeccionar Perfil`**

✅ **Verificación:** El icono quedará presionado/resaltado indicando que la herramienta está activa.

---

### Paso 2: Seleccionar una Capa y Feature

1. **Selecciona la capa** en el Panel de Capas (izquierda):
   - Debe ser una capa de **puntos** o **polígonos**
   - Haz clic sobre el nombre de la capa para seleccionarla

2. **Haz clic en un feature del mapa:**
   - Con la herramienta activa, el cursor cambiará a una mira/cruz
   - Haz **clic izquierdo** sobre cualquier punto o polígono en el mapa
   - Verás un **flash/destello** confirmando la selección

3. **Se abrirá automáticamente el panel "EdafoInteract Pro":**
   - Aparecerá en el lado **derecho** de la ventana de QGIS
   - Si no lo ves, ve a: `Vistas` → `Paneles` → `EdafoInteract Pro`

---

### Paso 3: Interfaz del Panel

El panel tiene **dos pestañas principales**:

#### 📝 Pestaña "Editor" (Predeterminada)

Esta pestaña se divide en dos áreas:

**Área Superior - Visualización Gráfica:**
- Muestra el perfil de suelo como un diagrama vertical
- Cada horizonte se representa con su color y textura únicos
- Puedes hacer scroll si el perfil es muy largo

**Área Inferior - Controles:**

1. **Selector de Capa:**
   - `Capa:` - Menú desplegable para seleccionar la capa de trabajo

2. **Información de Entidad:**
   - Muestra: `Entidad seleccionada ID: [número]`
   - O: `Ninguna entidad seleccionada`

3. **Lista de Horizontes:**
   - Muestra todos los horizontes del perfil actual
   - Formato: `Nombre | Profundidad (espesor) | Textura`
   - Cada item tiene el color de fondo del horizonte
   - **Doble clic** en un horizonte para editarlo

4. **Botones de Acción:**

   | Botón | Función |
   |-------|---------|
   | `↑` | Mueve el horizonte seleccionado hacia arriba |
   | `↓` | Mueve el horizonte seleccionado hacia abajo |
   | `Añadir Horizonte` | Crea un nuevo horizonte |
   | `Editar` | Modifica el horizonte seleccionado |
   | `Eliminar` | Borra el horizonte seleccionado |
   | `Limpiar Todo` | Elimina todos los horizontes del perfil |
   | `Guardar Perfil Capa` | Guarda como plantilla para esta capa |
   | `Aplicar a Entidad` | Aplica la plantilla al feature actual |
   | `Guardar en Entidad` | Guarda los cambios en el feature |

#### 🔍 Pestaña "Explorador"

- Lista todas las entidades de la capa seleccionada
- **Barra de búsqueda:** Filtra por ID o atributos
- **Checkbox "Solo con perfil":** Muestra solo entidades que ya tienen perfil guardado
- **Doble clic** en una entidad para cargarla en el Editor
- **Botón "Actualizar Lista":** Refresca la lista de entidades

---

### Paso 4: Añadir un Horizonte

1. Haz clic en el botón **`Añadir Horizonte`**

2. Se abrirá una ventana de diálogo. Completa los campos:

   | Campo | Descripción | Ejemplo |
   |-------|-------------|---------|
   | **Nombre** | Identificador del horizonte | `A`, `Bt`, `C` |
   | **Profundidad superior (cm)** | Dónde comienza el horizonte | `0` |
   | **Profundidad inferior (cm)** | Dónde termina el horizonte | `30` |
   | **Tipo de material** | Selecciona de la lista o escribe uno | `Arcilla` |
   | **Color** | Haz clic para elegir un color | Marrón |
   | **Tipo de límite** | Transición al siguiente horizonte | `abrupt` |

3. Haz clic en **`Aceptar`** para guardar

✅ El nuevo horizonte aparecerá en la lista y en la visualización gráfica.

---

### Paso 5: Editar un Horizonte Existente

**Método 1 - Doble clic:**
1. En la lista de horizontes, haz **doble clic** sobre el horizonte a editar
2. Se abrirá el diálogo de edición
3. Modifica los campos necesarios
4. Haz clic en **`Aceptar`**

**Método 2 - Botón Editar:**
1. Haz **clic izquierdo** para seleccionar el horizonte en la lista
2. Haz clic en el botón **`Editar`**
3. Modifica los campos necesarios
4. Haz clic en **`Aceptar`**

---

### Paso 6: Eliminar Horizontes

**Eliminar un horizonte:**
1. Selecciona el horizonte en la lista (clic izquierdo)
2. Haz clic en el botón **`Eliminar`**
3. Confirma en la ventana de diálogo: **`Sí`**

**Eliminar todos los horizontes:**
1. Haz clic en el botón **`Limpiar Todo`**
2. Confirma en la ventana de diálogo: **`Sí`**

---

### Paso 7: Guardar los Cambios

**Importante:** Los cambios se guardan automáticamente en la memoria del plugin, pero debes guardar explícitamente en la entidad:

1. Después de añadir/editar horizontes, haz clic en **`Guardar en Entidad`**
2. Verás un mensaje: `"Perfil guardado correctamente en la entidad"`
3. Los datos se almacenarán en el campo `edafo_horizons` de la tabla de atributos

---

### Paso 8: Usar Plantillas de Capa

**Guardar una plantilla:**
1. Crea un perfil de ejemplo con los horizontes deseados
2. Haz clic en **`Guardar Perfil Capa`**
3. El perfil se guarda como plantilla para esa capa específica

**Aplicar una plantilla a una entidad:**
1. Selecciona una entidad en el mapa (Paso 2)
2. Haz clic en **`Aplicar a Entidad`**
3. El perfil de plantilla se copiará a esta entidad
4. Haz clic en **`Guardar en Entidad`** para confirmar

---

### Paso 9: Desactivar la Herramienta

Para desactivar la herramienta de inspección:
1. Haz clic nuevamente en el icono **`Inspeccionar Perfil`** en la barra de herramientas
2. O ve al menú: `Complementos` → `EdafoInteract` → `Inspeccionar Perfil`

El panel se ocultará automáticamente.

## 💾 Almacenamiento de Datos

Los horizontes se almacenan en un campo JSON llamado `edafo_horizons` en la tabla de atributos del feature. Este campo se crea automáticamente la primera vez que añades un horizonte.

### Estructura del JSON:
```json
[
  {
    "name": "A",
    "top": 0,
    "bottom": 30,
    "color": "#8B4513",
    "texture": "Arcilla",
    "boundary_type": "abrupt"
  },
  {
    "name": "Bt",
    "top": 30,
    "bottom": 80,
    "color": "#A0522D",
    "texture": "Franco-arcilloso",
    "boundary_type": "clear"
  }
]
```

## 🎨 Tipos de Límite

- **Abrupto**: Transición < 2.5 cm (línea casi recta)
- **Claro**: Transición 2.5-7.5 cm (ligera ondulación)
- **Gradual**: Transición 7.5-12.5 cm (ondulación media)
- **Difuso**: Transición > 12.5 cm (ondulación pronunciada)

## 🖼️ Texturas de Materiales

Cada tipo de material tiene una textura única:
- **Arena**: Puntos dispersos
- **Arcilla**: Líneas diagonales
- **Limo**: Puntos en patrón regular
- **Franco**: Patrón de cruz
- **Grava**: Círculos pequeños
- **Roca**: Patrón de bloques
- **Materia orgánica/Turba**: Patrón denso de puntos

## 🔧 Configuración Técnica

### Estructura del Plugin
```
edafo_interact_v2/
├── __init__.py              # Inicialización del plugin
├── edafo_interact.py        # Clase principal
├── metadata.txt             # Metadatos del plugin
├── core/
│   ├── __init__.py
│   ├── map_tool.py          # Herramienta de selección
│   ├── profile_engine.py    # Motor de visualización
│   ├── horizon_manager.py   # Gestor de horizontes
│   └── materials.py         # Materiales predefinidos
├── ui/
│   ├── __init__.py
│   ├── profile_canvas.py    # Canvas de visualización
│   ├── profile_panel.py     # Panel principal
│   └── horizon_dialog.py    # Diálogo de edición
└── resources/
    └── icon.svg             # Icono del plugin
```

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Por favor:
1. Fork el repositorio
2. Crea una rama para tu feature
3. Commit tus cambios
4. Push a la rama
5. Crea un Pull Request

## 📝 Licencia

Este proyecto está bajo la licencia GPL v2.

## 👥 Autores

- **Felipe Flores** - Desarrollador principal

## 🐛 Reporte de Errores

Por favor reporta errores en: https://github.com/Felipe-Flores-creator/SoilTool/issues

## 📧 Contacto

- Email: felipe.ignacio.geo@gmail.com
- Repositorio: https://github.com/Felipe-Flores-creator/SoilTool

## 🔄 Historial de Versiones

### v1.0.4 (Actual)
- ✅ Gestión completa de horizontes con botones
- ✅ Materiales predefinidos y personalizados
- ✅ Almacenamiento en atributos del feature
- ✅ Texturas mejoradas para cada material
- ✅ Validación de solapamientos
- ✅ Interfaz mejorada con splitter

### v1.0.1
- Visualización básica de perfiles
- Herramienta de selección de features

### v1.0.0
- Versión inicial

## ❓ Preguntas Frecuentes y Solución de Problemas

### El plugin no aparece en QGIS después de instalarlo

**Solución:**
1. Verifica que la carpeta `edafo_interact_v2` esté en el directorio correcto de plugins
2. Reinicia QGIS completamente
3. Ve a `Complementos` → `Gestionar e instalar complementos` → pestaña `Instalados`
4. Busca "Edafo Interact V2" y asegúrate de que la casilla esté marcada ✓

### No puedo ver el panel "EdafoInteract Pro"

**Solución:**
1. Asegúrate de que la herramienta esté activada (icono presionado)
2. Selecciona una capa de puntos o polígonos
3. Haz clic en un feature del mapa
4. Si aún no aparece, ve a: `Vistas` → `Paneles` → `EdafoInteract Pro`

### El botón "Guardar en Entidad" está desactivado

**Causa:** No hay una entidad seleccionada en el mapa.

**Solución:**
1. Activa la herramienta "Inspeccionar Perfil"
2. Haz clic en un feature del mapa para seleccionarlo
3. Ahora el botón debería estar habilitado

### Los horizontes no se guardan correctamente

**Solución:**
1. Después de crear/editar horizontes, siempre haz clic en **`Guardar en Entidad`**
2. Verifica que el mensaje de confirmación aparezca
3. Abre la tabla de atributos de la capa y verifica que el campo `edafo_horizons` exista

### Error al validar horizontes (solapamiento)

**Causa:** Los horizontes no pueden superponerse en profundidad.

**Solución:**
1. Revisa que la profundidad inferior de un horizonte no sea mayor que la profundidad superior del siguiente
2. Ejemplo válido: Horizonte A (0-30 cm), Horizonte B (30-60 cm)
3. Ejemplo inválido: Horizonte A (0-30 cm), Horizonte B (25-55 cm) ← ¡Se solapan!

### No puedo seleccionar features en el mapa

**Solución:**
1. Verifica que la herramienta "Inspeccionar Perfil" esté activada
2. Asegúrate de que la capa esté seleccionada en el Panel de Capas
3. La capa debe ser de tipo **puntos** o **polígonos** (no funciona con líneas)

### El campo `edafo_horizons` no aparece en la tabla de atributos

**Solución:**
1. El campo se crea automáticamente al guardar el primer horizonte
2. Añade al menos un horizonte y haz clic en `Guardar en Entidad`
3. Abre la tabla de atributos: clic derecho en la capa → `Abrir tabla de atributos`
4. Si aún no aparece, guarda los cambios de la capa (Ctrl+S)

---

## 🙏 Agradecimientos

- A la comunidad de QGIS por su excelente trabajo
- A los usuarios que han probado y sugerido mejoras

---
Para alertar de posibles problemas comunicarse con Felipe.ignacio.geo@gmail.com
**¡Disfruta visualizando tus perfiles de suelo!** 🌱
