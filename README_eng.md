# SoilTool - QGIS Plugin for Soil Profile Visualization

**Spanish Description:**
(Para leer la versión en español, consulte el archivo [README.md](README.md))

SoilTool is a scientific QGIS plugin designed for the interactive visualization and management of soil profiles directly within vector layers. It allows users to define, edit, and visualize soil horizons with detailed properties including depth, texture, color, and boundary types. Data is stored efficiently using a sidecar JSON system, ensuring portability and performance.

---

# EdafoInteract v2 - QGIS Plugin for Soil Profile Visualization

QGIS Plugin that allows interactive visualization of soil profiles with complete management of horizons and strata.

## Key Features

### 🎯 Main Functionalities

1. **Feature Selection**: Click on any point or polygon in your vector layers to view its associated soil profile.

2. **Complete Horizon Management**:
   - Add new horizons with custom depths
   - Edit existing horizons
   - Delete individual horizons or all of them
   - Data is automatically saved in the feature's attributes

3. **Predefined Material Types**:
   - Clay
   - Sand
   - Silt
   - Loam
   - Clay Loam
   - Sandy Loam
   - Sandy Clay
   - Silty Clay
   - Gravel
   - Rock
   - Organic Matter
   - Peat

4. **Custom Materials**: You can type any material type if it's not in the predefined list.

5. **Advanced Visualization**:
   - Organic boundaries between horizons
   - Specific textures for each material type
   - Color gradients for greater realism
   - Boundary types: abrupt, clear, gradual, diffuse

## 📋 Requirements

- QGIS 3.0 or higher
- Python 3.x

## 🚀 Installation

### Method 1: Manual Installation (Recommended for development)

Follow these steps carefully:

#### Step 1: Locate the QGIS plugins directory

The plugins directory varies depending on your operating system:

| Operating System | Directory Path |
|------------------|----------------|
| **Windows** | `C:\Users\[YourUser]\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\` |
| **Linux** | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/` |
| **macOS** | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/` |

> **Note for Windows**: The `AppData` folder is hidden by default. To access it:
> 1. Open File Explorer
> 2. In the address bar, paste: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
> 3. Press Enter

#### Step 2: Copy the Plugin

1. Copy the entire `edafo_interact_v2` folder (with all its files and subfolders)
2. Paste the folder into the plugins directory identified in Step 1

#### Step 3: Activate the Plugin in QGIS

1. **Open QGIS** (or restart it if it was already open)
2. In the top menu, click on: **`Plugins`** → **`Manage and Install Plugins...`**
3. In the window that opens, select the **`Installed`** tab (left side)
4. Look in the list for: **`Edafo Interact V2`**
5. **Check the box** ✓ next to the name to activate it
6. Click **`Close`**

✅ **Done! The plugin is installed and active.**

---

### Method 2: Installation from ZIP (If available in the official repository)

1. In QGIS, go to: **`Plugins`** → **`Manage and Install Plugins...`**
2. Select the **`All`** tab
3. In the search bar, type: `Edafo Interact`
4. Select **`Edafo Interact V2`** from the list
5. Click the **`Install Plugin`** button
6. Wait for the installation to complete
7. Click **`Close`**

## 📖 Usage

### Step 1: Activate the Tool

Once the plugin is installed, you will see a new icon in the QGIS toolbar:

**Option A - From the toolbar:**
1. Look for the 🔍 **"Inspect Profile"** icon in the toolbar
2. **Left-click** on the icon to activate it

**Option B - From the menu:**
1. In the top menu, click on **`Plugins`**
2. In the drop-down menu, select **`EdafoInteract`**
3. Click on **`Inspect Profile`**

✅ **Verification:** The icon will remain pressed/highlighted indicating that the tool is active.

---

### Step 2: Select a Layer and Feature

1. **Select the layer** in the Layers Panel (left):
   - It must be a **point** or **polygon** layer
   - Click on the layer's name to select it

2. **Click on a feature on the map:**
   - With the tool active, the cursor will change to a crosshair
   - **Left-click** on any point or polygon on the map
   - You will see a **flash** confirming the selection

3. **The "EdafoInteract Pro" panel will open automatically:**
   - It will appear on the **right** side of the QGIS window
   - If you don't see it, go to: `View` → `Panels` → `EdafoInteract Pro`

---

### Step 3: Panel Interface

The panel has **two main tabs**:

#### 📝 "Editor" Tab (Default)

This tab is divided into two areas:

**Top Area - Graphical Visualization:**
- Shows the soil profile as a vertical diagram
- Each horizon is represented with its unique color and texture
- You can scroll if the profile is very long

**Bottom Area - Controls:**

1. **Layer Selector:**
   - `Layer:` - Drop-down menu to select the working layer

2. **Feature Information:**
   - Shows: `Selected feature ID: [number]`
   - Or: `No feature selected`

3. **Horizon List:**
   - Shows all horizons of the current profile
   - Format: `Name | Depth (thickness) | Texture`
   - Each item has the background color of the horizon
   - **Double-click** on a horizon to edit it

4. **Action Buttons:**

   | Button | Function |
   |--------|----------|
   | `↑` | Moves the selected horizon up |
   | `↓` | Moves the selected horizon down |
   | `Add Horizon` | Creates a new horizon |
   | `Edit` | Modifies the selected horizon |
   | `Delete` | Deletes the selected horizon |
   | `Clear All` | Removes all horizons from the profile |
   | `Save Layer Profile` | Saves as a template for this layer |
   | `Apply to Feature` | Applies the template to the current feature |
   | `Save to Feature` | Saves the changes to the feature |

#### 🔍 "Explorer" Tab

- Lists all features of the selected layer
- **Search bar:** Filter by ID or attributes
- **"With profile only" checkbox:** Shows only features that already have a saved profile
- **Double-click** on a feature to load it into the Editor
- **"Refresh List" button:** Refreshes the feature list

---

### Step 4: Add a Horizon

1. Click the **`Add Horizon`** button

2. A dialog window will open. Fill in the fields:

   | Field | Description | Example |
   |-------|-------------|---------|
   | **Name** | Horizon identifier | `A`, `Bt`, `C` |
   | **Top depth (cm)** | Where the horizon begins | `0` |
   | **Bottom depth (cm)** | Where the horizon ends | `30` |
   | **Material type** | Select from the list or type one | `Clay` |
   | **Color** | Click to choose a color | Brown |
   | **Boundary type** | Transition to the next horizon | `abrupt` |

3. Click **`OK`** to save

✅ The new horizon will appear in the list and in the graphical visualization.

---

### Step 5: Edit an Existing Horizon

**Method 1 - Double click:**
1. In the horizon list, **double-click** on the horizon to edit
2. The edit dialog will open
3. Modify the necessary fields
4. Click **`OK`**

**Method 2 - Edit Button:**
1. **Left-click** to select the horizon in the list
2. Click the **`Edit`** button
3. Modify the necessary fields
4. Click **`OK`**

---

### Step 6: Delete Horizons

**Delete one horizon:**
1. Select the horizon in the list (left-click)
2. Click the **`Delete`** button
3. Confirm in the dialog window: **`Yes`**

**Delete all horizons:**
1. Click the **`Clear All`** button
2. Confirm in the dialog window: **`Yes`**

---

### Step 7: Save Changes

**Important:** Changes are automatically saved in the plugin's memory, but you must explicitly save to the feature:

1. After adding/editing horizons, click on **`Save to Feature`**
2. You will see a message: `"Profile saved successfully to feature"`
3. The data will be stored in the `edafo_horizons` field of the attribute table

---

### Step 8: Use Layer Templates

**Save a template:**
1. Create a sample profile with the desired horizons
2. Click on **`Save Layer Profile`**
3. The profile is saved as a template for that specific layer

**Apply a template to a feature:**
1. Select a feature on the map (Step 2)
2. Click on **`Apply to Feature`**
3. The template profile will be copied to this feature
4. Click on **`Save to Feature`** to confirm

---

### Step 9: Deactivate the Tool

To deactivate the inspection tool:
1. Click again on the **`Inspect Profile`** icon in the toolbar
2. Or go to the menu: `Plugins` → `EdafoInteract` → `Inspect Profile`

The panel will hide automatically.

## 💾 Data Storage

Horizons are stored in a JSON field named `edafo_horizons` in the feature's attribute table. This field is automatically created the first time you add a horizon.

### JSON Structure:
```json
[
  {
    "name": "A",
    "top": 0,
    "bottom": 30,
    "color": "#8B4513",
    "texture": "Clay",
    "boundary_type": "abrupt"
  },
  {
    "name": "Bt",
    "top": 30,
    "bottom": 80,
    "color": "#A0522D",
    "texture": "Clay Loam",
    "boundary_type": "clear"
  }
]
```

## 🎨 Boundary Types

- **Abrupt**: Transition < 2.5 cm (almost straight line)
- **Clear**: Transition 2.5-7.5 cm (slight undulation)
- **Gradual**: Transition 7.5-12.5 cm (medium undulation)
- **Diffuse**: Transition > 12.5 cm (pronounced undulation)

## 🖼️ Material Textures

Each material type has a unique texture:
- **Sand**: Scattered dots
- **Clay**: Diagonal lines
- **Silt**: Dots in regular pattern
- **Loam**: Cross pattern
- **Gravel**: Small circles
- **Rock**: Block pattern
- **Organic Matter/Peat**: Dense dot pattern

## 🔧 Technical Configuration

### Plugin Structure
```
edafo_interact_v2/
├── __init__.py              # Plugin initialization
├── edafo_interact.py        # Main class
├── metadata.txt             # Plugin metadata
├── core/
│   ├── __init__.py
│   ├── map_tool.py          # Selection tool
│   ├── profile_engine.py    # Visualization engine
│   ├── horizon_manager.py   # Horizon manager
│   └── materials.py         # Predefined materials
├── ui/
│   ├── __init__.py
│   ├── profile_canvas.py    # Visualization canvas
│   ├── profile_panel.py     # Main panel
│   └── horizon_dialog.py    # Edit dialog
└── resources/
    └── icon.svg             # Plugin icon
```

## 🤝 Contributions

Contributions are welcome. Please:
1. Fork the repository
2. Create a branch for your feature
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## 📝 License

This project is licensed under the GPL v2 License.

## 👥 Authors

- **Felipe Flores** - Lead Developer

## 🐛 Bug Reporting

Please report bugs at: https://github.com/Felipe-Flores-creator/SoilTool/issues

## 📧 Contact

- Email: felipe.ignacio.geo@gmail.com
- Repository: https://github.com/Felipe-Flores-creator/SoilTool

## 🔄 Version History

### v1.0.4 (Current)
- ✅ Complete horizon management with buttons
- ✅ Predefined and custom materials
- ✅ Storage in feature attributes
- ✅ Improved textures for each material
- ✅ Overlap validation
- ✅ Improved interface with splitter

### v1.0.1
- Basic profile visualization
- Feature selection tool

### v1.0.0
- Initial release

## ❓ FAQ and Troubleshooting

### The plugin does not appear in QGIS after installing it

**Solution:**
1. Verify that the `edafo_interact_v2` folder is in the correct plugins directory
2. Restart QGIS completely
3. Go to `Plugins` → `Manage and Install Plugins` → `Installed` tab
4. Look for "Edafo Interact V2" and make sure the box is checked ✓

### I cannot see the "EdafoInteract Pro" panel

**Solution:**
1. Make sure the tool is activated (pressed icon)
2. Select a point or polygon layer
3. Click on a feature on the map
4. If it still does not appear, go to: `View` → `Panels` → `EdafoInteract Pro`

### The "Save to Feature" button is disabled

**Cause:** No feature is selected on the map.

**Solution:**
1. Activate the "Inspect Profile" tool
2. Click on a feature on the map to select it
3. Now the button should be enabled

### Horizons are not saving correctly

**Solution:**
1. After creating/editing horizons, always click on **`Save to Feature`**
2. Verify that the confirmation message appears
3. Open the layer's attribute table and verify that the `edafo_horizons` field exists

### Horizon validation error (overlap)

**Cause:** Horizons cannot overlap in depth.

**Solution:**
1. Check that the bottom depth of one horizon is not greater than the top depth of the next
2. Valid example: Horizon A (0-30 cm), Horizon B (30-60 cm)
3. Invalid example: Horizon A (0-30 cm), Horizon B (25-55 cm) ← They overlap!

### I cannot select features on the map

**Solution:**
1. Verify that the "Inspect Profile" tool is activated
2. Make sure the layer is selected in the Layers Panel
3. The layer must be of type **points** or **polygons** (does not work with lines)

### The `edafo_horizons` field does not appear in the attribute table

**Solution:**
1. The field is automatically created when saving the first horizon
2. Add at least one horizon and click on `Save to Feature`
3. Open the attribute table: right-click on the layer → `Open Attribute Table`
4. If it still doesn't appear, save the layer edits (Ctrl+S)

---

## 🙏 Acknowledgements

- To the QGIS community for their excellent work
- To the users who have tested and suggested improvements

---

**Enjoy visualizing your soil profiles!** 🌱
