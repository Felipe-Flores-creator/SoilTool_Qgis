# -*- coding: utf-8 -*-
"""
Diálogo para añadir/editar horizontes de suelo.
"""

from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QColorDialog,
    QPushButton,
    QDialogButtonBox,
    QMessageBox,
    QFileDialog,
    QScrollArea,
    QFrame,
    QWidget,
)
from qgis.PyQt.QtGui import QColor, QIntValidator
from qgis.PyQt.QtCore import Qt, QTimer

from ..core.profile_engine import HorizonData
from ..core.materials import (
    get_material_names,
    get_material_color,
    is_material_predefined,
)


class HorizonDialog(QDialog):
    """Diálogo para crear o editar un horizonte de suelo."""

    def __init__(self, parent=None, horizon=None):
        """
        Inicializa el diálogo.

        Args:
            parent: Widget padre
            horizon: Objeto HorizonData existente para editar, o None para crear nuevo
        """
        super().__init__(parent)
        self.horizon = horizon
        self.setup_ui()

        if horizon:
            self.populate_from_horizon(horizon)

    def setup_ui(self):
        """Configura la interfaz de usuario del diálogo."""
        self.setWindowTitle("Editar Horizonte" if self.horizon else "Nuevo Horizonte")
        self.setModal(True)
        self.setMinimumWidth(400)
        # Tamaño inicial: al abrir, asegurar que el layout/scroll se "calcule" y se vea completo
        self.resize(420, 500)
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # Contenedor con barra de desplazamiento para el formulario
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        form_layout = QFormLayout(scroll_content)
        form_layout.setSpacing(10)

        # Nombre del horizonte
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Ej: A, Bt, C, etc.")
        form_layout.addRow("Nombre:", self.name_edit)

        # Unidad de medida (cm / m)
        unit_layout = QHBoxLayout()
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["cm", "m"])
        self.unit_combo.setCurrentText("cm")
        self.unit_combo.currentTextChanged.connect(self._on_unit_changed)
        unit_layout.addWidget(self.unit_combo)
        unit_layout.addStretch()
        form_layout.addRow("Unidad:", unit_layout)

        # Profundidad superior
        self.top_spin = QDoubleSpinBox()
        self.top_spin.setRange(0, 10000)
        self.top_spin.setSuffix(" cm")
        self.top_spin.setDecimals(1)
        self.top_spin.setValue(0)
        form_layout.addRow("Profundidad superior:", self.top_spin)

        # Altura (Espesor)
        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(0, 10000)
        self.height_spin.setSuffix(" cm")
        self.height_spin.setDecimals(1)
        self.height_spin.setValue(30)
        form_layout.addRow("Altura (Espesor):", self.height_spin)

        # Profundidad inferior
        self.bottom_spin = QDoubleSpinBox()
        self.bottom_spin.setRange(0, 10000)
        self.bottom_spin.setSuffix(" cm")
        self.bottom_spin.setDecimals(1)
        self.bottom_spin.setValue(30)
        form_layout.addRow("Profundidad inferior:", self.bottom_spin)

        # Conectar señales para sincronización
        self._syncing = False
        self._unit_is_meters = False  # flag para saber si estamos en metros
        self.top_spin.valueChanged.connect(self._sync_from_top)
        self.bottom_spin.valueChanged.connect(self._sync_from_bottom)
        self.height_spin.valueChanged.connect(self._sync_from_height)

        # Tipo de material
        material_layout = QHBoxLayout()
        self.material_combo = QComboBox()
        self.material_combo.setEditable(True)
        self.material_combo.addItems(get_material_names())
        self.material_combo.setCurrentText("Arcilla")
        self.material_combo.currentTextChanged.connect(self.on_material_changed)
        material_layout.addWidget(self.material_combo)
        form_layout.addRow("Tipo de material:", material_layout)

        # Color
        color_layout = QHBoxLayout()
        self.color_button = QPushButton()
        self.color_button.setFixedHeight(30)
        self.color_button.setStyleSheet("background-color: #8B4513;")
        self.color_button.clicked.connect(self.choose_color)
        color_layout.addWidget(self.color_button)
        self.color_label = QLabel("#8B4513")
        self.color_label.setFixedWidth(80)
        color_layout.addWidget(self.color_label)
        color_layout.addStretch()
        form_layout.addRow("Color:", color_layout)

        # Simbología (Imagen)
        image_layout = QHBoxLayout()
        self.image_edit = QLineEdit()
        self.image_edit.setPlaceholderText(
            "Ruta al archivo (PNG, JPG, JPEG) (opcional)"
        )
        self.image_button = QPushButton("...")
        self.image_button.setFixedWidth(30)
        self.image_button.clicked.connect(self.browse_image)
        self.clear_image_button = QPushButton("X")
        self.clear_image_button.setFixedWidth(30)
        self.clear_image_button.clicked.connect(lambda: self.image_edit.clear())
        image_layout.addWidget(self.image_edit)
        image_layout.addWidget(self.image_button)
        image_layout.addWidget(self.clear_image_button)
        form_layout.addRow("Simbología (Imagen):", image_layout)

        # Tipo de límite inferior
        self.boundary_combo = QComboBox()
        self.boundary_combo.addItems(["abrupt", "clear", "gradual", "diffuse"])
        self.boundary_combo.setCurrentText("abrupt")
        self.boundary_combo.setToolTip(
            "abrupt: < 2.5 cm, clear: 2.5-7.5 cm, gradual: 7.5-12.5 cm, diffuse: > 12.5 cm"
        )
        form_layout.addRow("Tipo de límite:", self.boundary_combo)

        # --- PROPIEDADES GEOLÓGICAS ---
        form_layout.addRow(
            QLabel("<b>Propiedades Geológicas / Estratigrafía</b>"), QLabel("")
        )

        # Plegamiento
        self.folding_spin = QDoubleSpinBox()
        self.folding_spin.setRange(-200, 200)
        self.folding_spin.setSuffix(" px")
        self.folding_spin.setValue(0)
        self.folding_spin.setToolTip(
            "Curvatura del estrato (positivo: hacia arriba/anticlinal, negativo: hacia abajo/sinclinal)"
        )
        form_layout.addRow("Plegamiento (Curva):", self.folding_spin)

        # Falla
        self.fault_combo = QComboBox()
        self.fault_combo.addItem("Ninguna", "none")
        self.fault_combo.addItem("Normal (Falla Directa)", "normal")
        self.fault_combo.addItem("Inversa (Falla de Compresión)", "inverse")
        form_layout.addRow("Tipo de Falla:", self.fault_combo)

        self.fault_displacement_spin = QDoubleSpinBox()
        self.fault_displacement_spin.setRange(0, 500)
        self.fault_displacement_spin.setSuffix(" px")
        self.fault_displacement_spin.setValue(30)
        form_layout.addRow("Desplazamiento Falla:", self.fault_displacement_spin)

        # Inclinación
        self.inclination_spin = QDoubleSpinBox()
        self.inclination_spin.setRange(-85, 85)
        self.inclination_spin.setSuffix(" °")
        self.inclination_spin.setValue(0)
        self.inclination_spin.setToolTip(
            "Inclinación del horizonte (positivo: baja hacia la derecha, negativo: sube hacia la derecha)"
        )
        form_layout.addRow("Inclinación:", self.inclination_spin)

        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)

        # Botones
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

        # Forzar recalculo del layout inmediatamente para evitar que al abrir
        # el formulario se vea "recortado" (especialmente con QScrollArea).
        self.adjustSize()
        self.layout().activate()
        # Segundo "pulse" al event loop para que QScrollArea y el QFormLayout
        # recalculen correctamente al abrir el diálogo.
        QTimer.singleShot(0, self.adjustSize)

        # Nota: populate_from_horizon (si aplica) ocurre después del setup_ui()
        # para que el layout inicial ya esté correctamente renderizado.

    def _on_unit_changed(self, unit):
        """Cambia entre cm y m, ajustando suffix y factor de escala."""
        self._syncing = True
        if unit == "m":
            # Convertir valores actuales de cm a m
            self.top_spin.setValue(self.top_spin.value() / 100.0)
            self.height_spin.setValue(self.height_spin.value() / 100.0)
            self.bottom_spin.setValue(self.bottom_spin.value() / 100.0)
            self.top_spin.setSuffix(" m")
            self.height_spin.setSuffix(" m")
            self.bottom_spin.setSuffix(" m")
            self.top_spin.setDecimals(2)
            self.height_spin.setDecimals(2)
            self.bottom_spin.setDecimals(2)
            self._unit_is_meters = True
        else:
            # Convertir valores actuales de m a cm
            self.top_spin.setValue(self.top_spin.value() * 100.0)
            self.height_spin.setValue(self.height_spin.value() * 100.0)
            self.bottom_spin.setValue(self.bottom_spin.value() * 100.0)
            self.top_spin.setSuffix(" cm")
            self.height_spin.setSuffix(" cm")
            self.bottom_spin.setSuffix(" cm")
            self.top_spin.setDecimals(1)
            self.height_spin.setDecimals(1)
            self.bottom_spin.setDecimals(1)
            self._unit_is_meters = False
        self._syncing = False

    def _sync_from_top(self, val):
        """Sincroniza el fondo basado en el tope y la altura."""
        if self._syncing:
            return
        self._syncing = True
        height = self.height_spin.value()
        self.bottom_spin.setValue(val + height)
        self._syncing = False

    def _sync_from_bottom(self, val):
        """Sincroniza la altura basada en el fondo y el tope."""
        if self._syncing:
            return
        self._syncing = True
        top = self.top_spin.value()
        self.height_spin.setValue(max(0, val - top))
        self._syncing = False

    def _sync_from_height(self, val):
        """Sincroniza el fondo basado en el tope y la altura."""
        if self._syncing:
            return
        self._syncing = True
        top = self.top_spin.value()
        self.bottom_spin.setValue(top + val)
        self._syncing = False

    def on_material_changed(self, material_name):
        """Cambia el color cuando se selecciona un material diferente."""
        if is_material_predefined(material_name):
            color = get_material_color(material_name)
            self.set_color(color)

    def set_color(self, color):
        """Establece el color del horizonte."""
        self.color_button.setStyleSheet(f"background-color: {color.name()};")
        self.color_label.setText(color.name())
        self.current_color = color

    def choose_color(self):
        """Abre el diálogo de selección de color."""
        current_color = self.color_button.styleSheet().split("#")[1].split(";")[0]
        initial_color = QColor(f"#{current_color}")
        color = QColorDialog.getColor(initial_color, self, "Seleccionar Color")
        if color.isValid():
            self.set_color(color)

    def browse_image(self):
        """Abre un diálogo para buscar un archivo de imagen (PNG, JPG)."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar Simbología", "", "Imágenes (*.png *.jpg *.jpeg)"
        )
        if file_path:
            self.image_edit.setText(file_path)

    def populate_from_horizon(self, horizon):
        """Rellena los campos con los datos de un horizonte existente."""
        self.name_edit.setText(horizon.name)
        self.top_spin.setValue(horizon.top)
        self.bottom_spin.setValue(horizon.bottom)
        self.height_spin.setValue(horizon.bottom - horizon.top)
        self.material_combo.setCurrentText(horizon.texture)
        self.set_color(horizon.color)
        self.image_edit.setText(horizon.image_path if horizon.image_path else "")
        self.boundary_combo.setCurrentText(horizon.boundary_type)
        self.folding_spin.setValue(horizon.folding)

        # Seleccionar el tipo de falla basado en el dato interno
        index = self.fault_combo.findData(horizon.fault_type)
        if index >= 0:
            self.fault_combo.setCurrentIndex(index)

        self.fault_displacement_spin.setValue(horizon.fault_displacement)
        self.inclination_spin.setValue(getattr(horizon, "inclination", 0))

    def get_horizon(self):
        """
        Obtiene los datos del horizonte desde el diálogo.

        Returns:
            HorizonData: El horizonte creado o editado
        """
        name = self.name_edit.text().strip()
        if not name:
            name = f"H{int(self.top_spin.value())}-{int(self.bottom_spin.value())}"

        top = self.top_spin.value()
        bottom = self.bottom_spin.value()

        # Obtener material (puede ser personalizado)
        material = self.material_combo.currentText().strip()

        # Obtener color actual
        color_str = self.color_label.text()
        color = QColor(color_str)

        boundary_type = self.boundary_combo.currentText()
        folding = self.folding_spin.value()
        fault_type = self.fault_combo.currentData() or "none"
        fault_displacement = self.fault_displacement_spin.value()
        inclination = self.inclination_spin.value()
        image_path = self.image_edit.text().strip()
        if not image_path:
            image_path = None

        return HorizonData(
            name=name,
            top=top,
            bottom=bottom,
            color=color,
            texture=material,
            boundary_type=boundary_type,
            folding=folding,
            fault_type=fault_type,
            fault_displacement=fault_displacement,
            image_path=image_path,
            inclination=inclination,
        )

    def accept(self):
        """Valida los datos antes de aceptar."""
        # Se han relajado las restricciones según solicitud del usuario.
        # Solo aseguramos que el nombre no sea completamente nulo para evitar errores de visualización.
        if not self.name_edit.text().strip():
            self.name_edit.setText(f"H {self.top_spin.value()}")

        super().accept()
