# -*- coding: utf-8 -*-
"""
Panel mejorado para la gestión de horizontes de suelo con botones y lista.
"""

from qgis.PyQt.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QMessageBox,
    QSplitter,
    QFrame,
    QScrollArea,
    QLineEdit,
    QCheckBox,
    QTextEdit,
    QFileDialog,
    QMainWindow,
)
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtCore import Qt, pyqtSignal, QSize, QEvent, QObject, QTimer
from qgis.utils import iface

from qgis.gui import QgsMapLayerComboBox
from qgis.core import QgsMapLayerProxyModel
from .profile_canvas import EdafoCanvas
from .horizon_dialog import HorizonDialog
from ..core.horizon_manager import HorizonManager
from ..core.profile_engine import HorizonData
from ..core.report_generator import ReportGenerator


class ExplorerListWidget(QListWidget):
    """QListWidget personalizado que detecta cambios de visibilidad."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_visible = False

    def showEvent(self, event):
        """Se llama cuando el widget es mostrado (incluyendo cambio de pestaña)."""
        super().showEvent(event)
        # Llamar a actualización cuando se muestra
        self._update_if_needed()

    def _update_if_needed(self):
        """Actualiza el explorador si el widget es visible."""
        try:
            # Solo actualizar si cambió el estado de visibilidad
            is_visible = self.isVisible()
            if is_visible and not self._last_visible:
                self._last_visible = True
                panel = self._find_parent_panel()
                if panel and panel.current_layer:
                    panel.load_explorer_features()
            elif not is_visible:
                self._last_visible = False
        except:
            pass

    def _find_parent_panel(self):
        """Busca el ProfilePanel padre."""
        parent = self.parent()
        while parent:
            if hasattr(parent, "load_explorer_features"):
                return parent
            parent = parent.parent()
        return None


class ExplorerDockEventFilter(QObject):
    """Filtro de evento personalizado para detectar cambios en el dock del explorador."""

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.last_visible = False

    def eventFilter(self, obj, event):
        """Procesa eventos del dock del explorador."""
        # Detectar cambios de visibilidad
        if event.type() == QEvent.Show:
            if not self.last_visible:
                self.last_visible = True
                if self.panel and hasattr(self.panel, "load_explorer_features"):
                    try:
                        if self.panel.current_layer:
                            self.panel.load_explorer_features()
                    except:
                        pass
        elif event.type() == QEvent.Hide:
            self.last_visible = False

        return False  # Permitir que el evento continúe procesándose


class HorizonListItem(QListWidgetItem):
    """Item de lista personalizado para mostrar horizontes."""

    def __init__(self, horizon, index, parent=None):
        super().__init__(parent)
        self.horizon = horizon
        self.index = index
        self.update_text()
        self.update_color()

    def update_text(self):
        """Actualiza el texto del item."""
        thickness = self.horizon.bottom - self.horizon.top
        self.setText(
            f"{self.horizon.name} | {self.horizon.top:.1f} - {self.horizon.bottom:.1f} cm "
            f"({thickness:.1f} cm) | {self.horizon.texture}"
        )

    def update_color(self):
        """Actualiza el color de fondo del item."""
        # Crear un gradiente sutil para el fondo
        color = self.horizon.color
        lighter_color = color.lighter(120)
        self.setBackground(color)
        self.setForeground(
            QColor("white") if color.lightness() < 120 else QColor("black")
        )


class ProfilePanel(QWidget):
    """Panel principal para la visualización y gestión de perfiles de suelo."""

    # Señal emitida cuando se modifican los horizontes
    horizonsChanged = pyqtSignal(list)
    # Señal para solicitar activación del seleccionador en mapa
    requestMapToolActivation = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_feature = None
        self.current_layer = None
        self.horizons = []

        # Referencias a los docks (se asignarán desde edafo_interact.py)
        self.dock_editor = None
        self.dock_canvas = None
        self.dock_explorer = None
        self.dock_dem_profile = None
        # Referencia a la instancia principal del plugin (se asignará desde edafo_interact.py)
        self.plugin_instance = None

        self.setup_ui()

    def setup_ui(self):
        """Configura la interfaz de usuario dividida en componentes separados."""
        # --- 1. LIENZO 2D (CANVAS) ---
        self.canvas_widget = QScrollArea()
        self.canvas_widget.setWidgetResizable(True)
        self.canvas_widget.setMinimumHeight(250)
        self.canvas = EdafoCanvas()
        self.canvas_widget.setWidget(self.canvas)

        # --- 2. EDITOR DE PERFIL (Este propio widget) ---
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        editor_layout = QVBoxLayout(scroll_content)
        editor_layout.setContentsMargins(5, 5, 5, 5)

        # Selección de capa (está en el editor pero afecta a todo)
        layer_layout = QHBoxLayout()
        layer_label = QLabel("Capa:")
        self.layer_combo = QgsMapLayerComboBox()
        # QGIS: QgsMapLayerComboBox.setFilters() está deprecated en tu versión.
        # Para evitar warnings, solo aplicamos filtros si existe una API no-deprecated
        # (setItemTypeFilters). Si no existe, dejamos el combobox sin filtros.
        layer_types = (
            QgsMapLayerProxyModel.PolygonLayer | QgsMapLayerProxyModel.PointLayer
        )
        try:
            if hasattr(self.layer_combo, "setItemTypeFilters"):
                self.layer_combo.setItemTypeFilters(layer_types)
            # else: no llamar setFilters() para evitar DeprecationWarning
        except Exception:
            # Último recurso: sin filtros para no romper la UI.
            pass

        self.layer_combo.layerChanged.connect(self.on_layer_combo_changed)
        layer_layout.addWidget(layer_label)
        layer_layout.addWidget(self.layer_combo)
        editor_layout.addLayout(layer_layout)

        # Info de entidad
        self.feature_info_label = QLabel("Ninguna entidad seleccionada")
        self.feature_info_label.setStyleSheet(
            "color: #2c3e50; font-weight: bold; margin: 5px 0;"
        )
        editor_layout.addWidget(self.feature_info_label)

        # Botón para activar el seleccionador en mapa (solo ícono)
        select_map_layout = QHBoxLayout()
        import os

        # Usa el ícono existente (no se crea un nuevo archivo) para mantener la funcionalidad
        # del botón sin modificar la lógica del tool.
        crosshair_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "resources", "crosshair.svg"
        )
        self.select_map_button = QPushButton()
        self.select_map_button.setIcon(QIcon(crosshair_path))
        self.select_map_button.setIconSize(QSize(16, 16))
        self.select_map_button.setToolTip(
            "Seleccionar Entidad en Mapa\nHaga click para activar el seleccionador y luego click en la entidad del mapa"
        )
        self.select_map_button.setFixedSize(30, 30)
        self.select_map_button.setStyleSheet(
            """
            QPushButton {
                background-color: #3498db;
                color: white;
                font-weight: bold;
                padding: 2px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:checked {
                background-color: #e74c3c;
            }
        """
        )
        self.select_map_button.setCheckable(True)
        self.select_map_button.clicked.connect(self.on_select_map_clicked)
        select_map_layout.addWidget(self.select_map_button)
        select_map_layout.addStretch()
        editor_layout.addLayout(select_map_layout)

        # Configuración del Perfil (ID y Descripción)
        profile_config_layout = QVBoxLayout()
        profile_config_layout.setSpacing(2)

        id_layout = QHBoxLayout()
        id_layout.addWidget(QLabel("ID del Perfil:"))
        self.profile_id_edit = QLineEdit()
        self.profile_id_edit.setPlaceholderText("Ej: Calicata-01")
        id_layout.addWidget(self.profile_id_edit)
        profile_config_layout.addLayout(id_layout)

        profile_config_layout.addWidget(QLabel("Descripción / Atributos del Suelo:"))
        self.profile_desc_edit = QTextEdit()
        self.profile_desc_edit.setPlaceholderText(
            "Notas sobre la calicata, clasificación, fecha, autor, etc."
        )
        self.profile_desc_edit.setMaximumHeight(60)
        profile_config_layout.addWidget(self.profile_desc_edit)

        editor_layout.addLayout(profile_config_layout)

        # Lista de horizontes y botones de reordenamiento
        list_reorder_layout = QHBoxLayout()
        self.horizon_list = QListWidget()
        self.horizon_list.setMinimumHeight(150)
        self.horizon_list.itemDoubleClicked.connect(self.edit_selected_horizon)
        self.horizon_list.itemSelectionChanged.connect(self.on_selection_changed)
        list_reorder_layout.addWidget(self.horizon_list)

        reorder_btn_layout = QVBoxLayout()
        self.up_button = QPushButton("↑")
        self.up_button.setFixedSize(30, 28)
        self.up_button.clicked.connect(self.move_selected_up)
        self.down_button = QPushButton("↓")
        self.down_button.setFixedSize(30, 28)
        self.down_button.clicked.connect(self.move_selected_down)
        reorder_btn_layout.addWidget(self.up_button)
        reorder_btn_layout.addWidget(self.down_button)
        reorder_btn_layout.addStretch()
        list_reorder_layout.addLayout(reorder_btn_layout)
        editor_layout.addLayout(list_reorder_layout)

        # Acciones de plantilla
        template_layout = QHBoxLayout()
        self.save_template_button = QPushButton("Guardar como Plantilla")
        self.save_template_button.setFixedHeight(31)
        self.save_template_button.clicked.connect(self.save_layer_template)
        self.apply_template_button = QPushButton("Aplicar")
        self.apply_template_button.setFixedHeight(31)
        self.apply_template_button.clicked.connect(self.apply_layer_template)
        template_layout.addWidget(self.save_template_button)
        template_layout.addWidget(self.apply_template_button)
        editor_layout.addLayout(template_layout)

        horiz_actions_layout = QHBoxLayout()
        self.add_button = QPushButton("Añadir")
        self.add_button.setFixedHeight(31)
        self.add_button.clicked.connect(self.add_horizon)
        self.edit_button = QPushButton("Editar")
        self.edit_button.setFixedHeight(31)
        self.edit_button.clicked.connect(self.edit_selected_horizon)
        self.delete_button = QPushButton("Eliminar")
        self.delete_button.setFixedHeight(31)
        self.delete_button.clicked.connect(self.delete_selected_horizon)
        self.clear_button = QPushButton("Limpiar")
        self.clear_button.setFixedHeight(31)
        self.clear_button.clicked.connect(self.clear_all_horizons)

        horiz_actions_layout.addWidget(self.add_button)
        horiz_actions_layout.addWidget(self.edit_button)
        horiz_actions_layout.addWidget(self.delete_button)
        horiz_actions_layout.addWidget(self.clear_button)
        editor_layout.addLayout(horiz_actions_layout)

        self.depth_label = QLabel("Profundidad total: 0 cm")
        self.depth_label.setStyleSheet("color: gray; font-style: italic;")
        editor_layout.addWidget(self.depth_label)

        # Botón de Guardado Explícito (Prioridad según requerimiento)
        self.save_profile_button = QPushButton("Guardar Perfil")
        self.save_profile_button.setFixedHeight(31)
        self.save_profile_button.setStyleSheet(
            """
            QPushButton {
                background-color: #27ae60;
                color: white;
                font-size: 10px;
                font-weight: bold;
                padding: 2px 10px;
                border-radius: 4px;
                margin: 4px 0;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
            }
        """
        )
        self.save_profile_button.clicked.connect(self.save_current_profile)
        editor_layout.addWidget(self.save_profile_button)

        # Acciones de Exportación
        export_layout = QHBoxLayout()
        self.export_img_button = QPushButton("Exportar")
        self.export_img_button.setFixedHeight(31)
        self.export_img_button.setToolTip("Exporta el perfil actual como PNG")
        self.export_img_button.clicked.connect(self.export_profile_image)

        self.pdf_report_button = QPushButton("PDF")
        self.pdf_report_button.setFixedHeight(31)
        self.pdf_report_button.setToolTip(
            "Genera un informe PDF nativo de toda la capa"
        )
        self.pdf_report_button.clicked.connect(self.generate_layer_pdf_report)

        export_layout.addWidget(self.export_img_button)
        export_layout.addWidget(self.pdf_report_button)
        editor_layout.addLayout(export_layout)

        # Control de visualización de falla
        self.show_fault_check = QCheckBox("Visualizar Plano de Falla (Rojo)")
        self.show_fault_check.toggled.connect(self.on_show_fault_toggled)

        # Opción de auto-encadenar
        self.auto_chain_check = QCheckBox("Auto-encadenar profundidades")
        self.auto_chain_check.setChecked(True)
        self.auto_chain_check.setToolTip(
            "Ajusta automáticamente las profundidades para que no haya huecos ni solapamientos."
        )

        # Control de visualización de paneles adicionales
        self.show_canvas_check = QCheckBox("Mostrar Lienzo 2D")
        self.show_canvas_check.setChecked(True)
        self.show_canvas_check.toggled.connect(self.on_show_canvas_toggled)

        self.show_explorer_check = QCheckBox("Mostrar Explorador")
        self.show_explorer_check.setChecked(True)
        self.show_explorer_check.toggled.connect(self.on_show_explorer_toggled)

        self.show_dem_profile_check = QCheckBox("Mostrar Perfil Topográfico")
        self.show_dem_profile_check.setChecked(True)
        self.show_dem_profile_check.toggled.connect(self.on_show_dem_profile_toggled)

        editor_layout.addWidget(self.show_fault_check)
        editor_layout.addWidget(self.auto_chain_check)
        editor_layout.addWidget(self.show_canvas_check)
        editor_layout.addWidget(self.show_explorer_check)
        editor_layout.addWidget(self.show_dem_profile_check)

        self.scroll_area.setWidget(scroll_content)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.scroll_area)

        # --- 3. EXPLORADOR DE ENTIDADES ---
        self.explorer_widget = QWidget()
        explorer_layout = QVBoxLayout()
        explorer_layout.setContentsMargins(5, 5, 5, 5)

        explorer_layout.addWidget(QLabel("Explorar todas las entidades de la capa:"))

        # Búsqueda y filtros
        filter_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar por ID o atributos...")
        self.search_edit.textChanged.connect(self.filter_explorer)
        filter_layout.addWidget(self.search_edit)

        self.profile_only_check = QCheckBox("Solo con perfil")
        self.profile_only_check.stateChanged.connect(self.filter_explorer)
        filter_layout.addWidget(self.profile_only_check)
        explorer_layout.addLayout(filter_layout)

        # Lista de entidades
        self.explorer_list = ExplorerListWidget()
        self.explorer_list.itemDoubleClicked.connect(
            self.on_explorer_item_double_clicked
        )
        explorer_layout.addWidget(self.explorer_list)

        self.refresh_explorer_btn = QPushButton("Actualizar Lista")
        self.refresh_explorer_btn.setFixedHeight(28)
        self.refresh_explorer_btn.clicked.connect(self.load_explorer_features)
        explorer_layout.addWidget(self.refresh_explorer_btn)

        self.explorer_widget.setLayout(explorer_layout)

    def on_selection_changed(self):
        """Maneja el cambio de selección en la lista."""
        selected_indices = [
            self.horizon_list.row(i) for i in self.horizon_list.selectedItems()
        ]
        has_selection = len(selected_indices) > 0
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)

        # Habilitar botones de reordenamiento
        if has_selection:
            index = selected_indices[0]
            self.up_button.setEnabled(index > 0)
            self.down_button.setEnabled(index < self.horizon_list.count() - 1)
        else:
            self.up_button.setEnabled(False)
            self.down_button.setEnabled(False)

    def on_select_map_clicked(self, checked):
        """
        Maneja el click en el botón de selección en mapa.
        Activa o desactiva la herramienta de mapa para seleccionar entidades.
        Solo selecciona polígonos o puntos - NO abre el panel de perfil topográfico.
        """
        if checked:
            # Activar la herramienta de mapa
            if self.plugin_instance:
                self.plugin_instance.activate_map_tool()
            else:
                # Si no hay referencia al plugin, intentar usar iface directamente
                # Esto es un fallback por si el botón se usa sin la integración completa
                try:
                    from qgis.utils import iface
                    from ..core.map_tool import SoilMapTool

                    map_tool = SoilMapTool(iface.mapCanvas())
                    map_tool.featureSelected.connect(self._on_feature_selected)
                    iface.mapCanvas().setMapTool(map_tool)
                except Exception as e:
                    QMessageBox.warning(
                        self,
                        "Error",
                        f"No se pudo activar el seleccionador: {str(e)}",
                    )
                    self.select_map_button.setChecked(False)
        else:
            # Desactivar la herramienta de mapa
            if self.plugin_instance:
                self.plugin_instance.deactivate_map_tool()

    def _on_feature_selected(self, data):
        """
        Slot para manejar la selección de una entidad desde la herramienta de mapa.
        Este método se usa cuando el botón de selección se usa sin la integración completa.
        """
        feature = data["feature"]
        layer = data["layer"]
        self.set_feature(feature, layer)

    def set_feature(self, feature, layer):
        """
        Establece el feature actual y carga sus horizontes.

        Args:
            feature: QgsFeature de QGIS
            layer: QgsVectorLayer donde está el feature
        """
        if feature and layer:
            # Asegurar que el objeto feature tenga acceso a todos los campos actuales de la capa
            feature.setFields(layer.fields())

        self.current_layer = layer

        # Sincronizar el combo de capas si es necesario
        if layer and self.layer_combo.currentLayer() != layer:
            self.layer_combo.blockSignals(True)
            self.layer_combo.setLayer(layer)
            self.layer_combo.blockSignals(False)

        # Actualizar info de entidad
        if feature and feature.isValid():
            # Re-cargar el feature FRESCO desde la capa por su FID para garantizar
            # que los atributos reflejan lo guardado en disco (no la copia en memoria del evento)
            fresh_feature = layer.getFeature(feature.id())
            if fresh_feature.isValid():
                self.current_feature = fresh_feature
            else:
                self.current_feature = feature  # fallback al original si falla

            self.feature_info_label.setText(
                f"Entidad seleccionada ID: {self.current_feature.id()}"
            )
            # Cargar horizontes vinculados a esta entidad específica
            profile_id, description, self.horizons = HorizonManager.get_profile_data(
                self.current_feature, layer
            )
            self.profile_id_edit.setText(str(profile_id) if profile_id != -1 else "")
            self.profile_desc_edit.setPlainText(description)
        else:
            self.feature_info_label.setText("Ninguna entidad seleccionada")
            self.horizons = []
            self.profile_id_edit.setText("")
            self.profile_desc_edit.setPlainText("")

        self.update_ui()

    def on_show_fault_toggled(self, checked):
        """Maneja el cambio en el checkbox de visualización de falla."""
        self.canvas.show_fault_line = checked
        self.canvas.update()

    def on_show_canvas_toggled(self, checked):
        """Maneja la visibilidad del Lienzo 2D desde el checkbox."""
        if self.dock_canvas:
            self.dock_canvas.setVisible(checked)
            QTimer.singleShot(0, self._refresh_tabified_docks)

    def on_show_explorer_toggled(self, checked):
        """Maneja la visibilidad del Explorador desde el checkbox."""
        if self.dock_explorer:
            self.dock_explorer.setVisible(checked)
            QTimer.singleShot(0, self._refresh_tabified_docks)

    def on_show_dem_profile_toggled(self, checked):
        """Maneja la visibilidad del Perfil Topográfico desde el checkbox."""
        if self.dock_dem_profile:
            self.dock_dem_profile.setVisible(checked)

    def on_canvas_visibility_changed(self, visible):
        """Actualiza el checkbox del Lienzo 2D cuando la visibilidad del dock cambia externamente."""
        self.show_canvas_check.blockSignals(True)
        self.show_canvas_check.setChecked(visible)
        self.show_canvas_check.blockSignals(False)
        # Diferir la tabificación al siguiente ciclo del event loop para evitar
        # access violation al llamar tabifyDockWidget durante hideChildren de Qt
        QTimer.singleShot(0, self._refresh_tabified_docks)

    def on_explorer_visibility_changed(self, visible):
        """Actualiza el checkbox del Explorador cuando la visibilidad del dock cambia externamente."""
        self.show_explorer_check.blockSignals(True)
        self.show_explorer_check.setChecked(visible)
        self.show_explorer_check.blockSignals(False)
        # Diferir la tabificación al siguiente ciclo del event loop para evitar
        # access violation al llamar tabifyDockWidget durante hideChildren de Qt
        QTimer.singleShot(0, self._refresh_tabified_docks)
        # Refresca el contenido del explorador cuando se hace visible
        if visible:
            self.load_explorer_features()

    def on_dem_profile_visibility_changed(self, visible):
        """Actualiza el checkbox del Perfil Topográfico cuando la visibilidad del dock cambia externamente."""
        self.show_dem_profile_check.blockSignals(True)
        self.show_dem_profile_check.setChecked(visible)
        self.show_dem_profile_check.blockSignals(False)

    def _refresh_tabified_docks(self):
        """Asegura que los docks del editor, canvas y explorador se tabifiquen sólo cuando corresponda."""
        try:
            if not self.dock_editor:
                return

            # Buscar explícitamente una QMainWindow en la jerarquía de padres
            main_window = self.dock_editor.window()
            if not isinstance(main_window, QMainWindow):
                return

            visible_docks = []
            if self.dock_canvas and self.dock_canvas.isVisible():
                visible_docks.append(self.dock_canvas)
            if self.dock_explorer and self.dock_explorer.isVisible():
                visible_docks.append(self.dock_explorer)

            if len(visible_docks) >= 2:
                main_window.tabifyDockWidget(self.dock_editor, visible_docks[0])
                main_window.tabifyDockWidget(visible_docks[0], visible_docks[1])
        except Exception:
            # Captura defensiva: si Qt ya destruyó algún widget, no crashear
            pass

    def update_ui(self):
        """Actualiza toda la interfaz con los horizontes actuales."""
        # Actualizar canvas
        self.canvas.set_data(self.horizons)

        # Actualizar lista
        self.horizon_list.clear()
        for i, horizon in enumerate(self.horizons):
            item = HorizonListItem(horizon, i)
            self.horizon_list.addItem(item)

        # Actualizar profundidad total
        if self.horizons:
            max_depth = max(h.bottom for h in self.horizons)
            self.depth_label.setText(f"Profundidad total: {max_depth:.1f} cm")
        else:
            self.depth_label.setText("Profundidad total: 0 cm")

        # Actualizar estado de botones
        has_feature = self.current_feature is not None
        self.add_button.setEnabled(
            True
        )  # Permitir añadir aunque no haya feature (para plantillas)
        has_horizons = len(self.horizons) > 0
        self.clear_button.setEnabled(has_horizons)
        self.edit_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.save_template_button.setEnabled(has_horizons)
        self.apply_template_button.setEnabled(has_feature)
        self.save_profile_button.setEnabled(has_feature)
        self.export_img_button.setEnabled(has_horizons)
        self.pdf_report_button.setEnabled(self.current_layer is not None)

    def add_horizon(self):
        """Abre el diálogo para añadir un nuevo horizonte."""
        # Sugerir profundidad basada en el último horizonte
        default_top = 0
        default_bottom = 30
        if self.horizons:
            last_horizon = self.horizons[-1]
            default_top = last_horizon.bottom
            default_bottom = default_top + 30

        dialog = HorizonDialog(self)
        dialog.top_spin.setValue(default_top)
        dialog.bottom_spin.setValue(default_bottom)

        if dialog.exec_() == HorizonDialog.Accepted:
            new_horizon = dialog.get_horizon()

            # Si auto-encadenar está activo, ajustamos el nuevo horizonte
            if self.auto_chain_check.isChecked() and self.horizons:
                new_horizon.top = self.horizons[-1].bottom
                new_horizon.bottom = new_horizon.top + (
                    dialog.bottom_spin.value() - dialog.top_spin.value()
                )

            # Validar (opcional ahora que reencadenamos, pero bueno mantenerlo)
            is_valid, error_msg = HorizonManager.validate_horizons(
                self.horizons + [new_horizon]
            )

            # Si no es válido y auto-encadenar está off, avisar
            if not is_valid and not self.auto_chain_check.isChecked():
                QMessageBox.warning(self, "Error de validación", error_msg)
                return

            # Añadir horizonte
            self.horizons.append(new_horizon)

            # Re-encadenar todo si está activo
            if self.auto_chain_check.isChecked():
                self.horizons = HorizonManager.rechain_horizons(self.horizons)

            # ELIMINADO GUARDADO AUTOMÁTICO - Ahora se usa el botón "Guardar Perfil"

            self.update_ui()
            self.horizonsChanged.emit(self.horizons)

            # Actualizar indicador en el explorador
            self.load_explorer_features()

    def edit_selected_horizon(self):
        """Edita el horizonte seleccionado en la lista."""
        selected_items = self.horizon_list.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        index = item.index

        dialog = HorizonDialog(self, self.horizons[index])

        if dialog.exec_() == HorizonDialog.Accepted:
            new_horizon = dialog.get_horizon()
            self.horizons[index] = new_horizon

            # Re-encadenar todo si está activo
            if self.auto_chain_check.isChecked():
                self.horizons = HorizonManager.rechain_horizons(self.horizons)
            else:
                # Si no está activo, al menos validamos
                is_valid, error_msg = HorizonManager.validate_horizons(self.horizons)
                if not is_valid:
                    QMessageBox.warning(self, "Error de validación", error_msg)
                    # Opcional: revertir cambio si no es válido
                    # return

            # ELIMINADO GUARDADO AUTOMÁTICO - Ahora se usa el botón "Guardar Perfil"

            self.update_ui()
            self.horizonsChanged.emit(self.horizons)

            # Actualizar indicador en el explorador
            self.load_explorer_features()

    def delete_selected_horizon(self):
        """Elimina el horizonte seleccionado."""
        selected_items = self.horizon_list.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        index = item.index

        reply = QMessageBox.question(
            self,
            "Confirmar eliminación",
            f"¿Está seguro de eliminar el horizonte '{self.horizons[index].name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            # ELIMINADO GUARDADO AUTOMÁTICO - Ahora se usa el botón "Guardar Perfil"
            self.horizons.pop(index)
            self.update_ui()
            self.horizonsChanged.emit(self.horizons)

            # Actualizar indicador en el explorador
            self.load_explorer_features()

    def clear_all_horizons(self):
        """Elimina todos los horizontes del feature actual."""
        if not self.horizons:
            return

        reply = QMessageBox.question(
            self,
            "Confirmar eliminación",
            "¿Está seguro de eliminar TODOS los horizontes del perfil?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            # ELIMINADO GUARDADO AUTOMÁTICO - Ahora se usa el botón "Guardar Perfil"
            self.horizons = []
            self.update_ui()
            self.horizonsChanged.emit(self.horizons)

            # Actualizar indicador en el explorador
            self.load_explorer_features()

    def move_selected_up(self):
        """Mueve el horizonte seleccionado una posición hacia arriba."""
        index = self.horizon_list.currentRow()
        if index > 0:
            self.horizons[index], self.horizons[index - 1] = (
                self.horizons[index - 1],
                self.horizons[index],
            )

            # Re-encadenar si está activo
            if self.auto_chain_check.isChecked():
                self.horizons = HorizonManager.rechain_horizons(self.horizons)

            # ELIMINADO GUARDADO AUTOMÁTICO - Ahora se usa el botón "Guardar Perfil"
            self.update_ui()
            self.horizon_list.setCurrentRow(index - 1)
            self.horizonsChanged.emit(self.horizons)

    def move_selected_down(self):
        """Mueve el horizonte seleccionado una posición hacia abajo."""
        index = self.horizon_list.currentRow()
        if index < len(self.horizons) - 1:
            self.horizons[index], self.horizons[index + 1] = (
                self.horizons[index + 1],
                self.horizons[index],
            )

            # Re-encadenar si está activo
            if self.auto_chain_check.isChecked():
                self.horizons = HorizonManager.rechain_horizons(self.horizons)

            # ELIMINADO GUARDADO AUTOMÁTICO - Ahora se usa el botón "Guardar Perfil"
            self.update_ui()
            self.horizon_list.setCurrentRow(index + 1)
            self.horizonsChanged.emit(self.horizons)

    def save_layer_template(self):
        """Guarda los horizontes actuales como plantilla para la capa seleccionada."""
        layer = self.layer_combo.currentLayer()
        if not layer:
            QMessageBox.warning(self, "Error", "Debe seleccionar una capa.")
            return

        HorizonManager.save_layer_profile(layer, self.horizons)
        QMessageBox.information(
            self,
            "Perfil Guardado",
            f"Se ha guardado el perfil para la capa '{layer.name()}'.",
        )

    def apply_layer_template(self):
        """Aplica la plantilla de la capa al feature actual."""
        if not self.current_feature or not self.current_layer:
            QMessageBox.warning(
                self, "Error", "Debe seleccionar una entidad en el mapa."
            )
            return

        template_horizons = HorizonManager.get_layer_profile(self.current_layer)
        if not template_horizons:
            QMessageBox.warning(
                self, "Sin Perfil", "Esta capa no tiene un perfil guardado."
            )
            return
        self.horizons = template_horizons
        # ELIMINADO GUARDADO AUTOMÁTICO - El usuario debe presionar "Guardar Perfil" para persistir
        self.update_ui()
        self.horizonsChanged.emit(self.horizons)
        self.load_explorer_features()

    def save_current_profile(self):
        """Guarda los horizontes actuales en la entidad seleccionada."""
        if not self.current_feature or not self.current_layer:
            QMessageBox.warning(
                self,
                "Error",
                "Debe seleccionar una entidad en el mapa para guardar el perfil.",
            )
            return

        profile_id = self.profile_id_edit.text().strip()
        description = self.profile_desc_edit.toPlainText().strip()

        success = HorizonManager.save_profile_data(
            self.current_feature,
            self.current_layer,
            profile_id,
            description,
            self.horizons,
        )

        if success:
            # Re-cargar el feature fresco para sincronizar el estado interno
            fresh = self.current_layer.getFeature(self.current_feature.id())
            if fresh.isValid():
                self.current_feature = fresh

            QMessageBox.information(
                self,
                "Perfil Guardado",
                f"El perfil ha sido guardado exitosamente para la entidad ID: {self.current_feature.id()}.",
            )
            # Actualizar la interfaz y el explorador
            self.update_ui()
            self.load_explorer_features()
            # Emitir señal para notificar a otros componentes
            self.horizonsChanged.emit(self.horizons)
        else:
            QMessageBox.critical(
                self,
                "Error",
                "No se pudo guardar el perfil en la entidad. Verifique si la capa es editable o si hay restricciones de permisos.",
            )

    def on_layer_combo_changed(self, layer):
        """Maneja el cambio de capa en el combo box."""
        # Al cambiar de capa, limpiamos la selección de entidad actual
        # para cumplir con el requisito de interfaz vacía hasta selección explícita
        self.current_feature = None
        self.current_layer = layer

        # Resetear horizontes a una lista vacía al cambiar de capa (sin selección de punto)
        # El usuario puede usar "Aplicar a Entidad" más tarde si hay una plantilla
        self.horizons = []
        self.profile_id_edit.setText("")
        self.profile_desc_edit.setPlainText("")
        self.update_ui()

        # Requisito: Al elegir el archivo (capa), el plugin asegura que tenga el campo edafo_id
        if layer:
            HorizonManager.ensure_id_field(layer)

        # Actualizar el explorador de la nueva capa
        self.load_explorer_features()

    def load_explorer_features(self):
        """Carga todas las entidades de la capa en el explorador."""
        self.explorer_list.clear()
        if not self.current_layer:
            return

        # Para capas muy grandes, esto podría ser lento.
        # Podríamos limitar a las primeras 1000 o usar un modelo perezoso.
        features = self.current_layer.getFeatures()

        for feature in features:
            fid = feature.id()
            horizons = HorizonManager.get_horizons(feature, self.current_layer)
            has_profile = len(horizons) > 0

            # Crear item de lista
            # Intentar buscar un nombre descriptivo en los atributos
            display_name = f"FID: {fid}"
            for attr in ["name", "nombre", "id", "label"]:
                idx = feature.fields().indexOf(attr)
                if idx != -1:
                    val = feature.attribute(idx)
                    if val:
                        display_name = f"{val} ({fid})"
                        break

            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, fid)

            if has_profile:
                item.setIcon(QIcon())  # Podríamos añadir un icono de perfil
                item.setBackground(QColor("#e8f8f5"))
                item.setToolTip("Esta entidad tiene un perfil guardado.")

            self.explorer_list.addItem(item)

        self.filter_explorer()

    def filter_explorer(self):
        """Filtra la lista del explorador basada en la búsqueda y el checkbox."""
        search_text = self.search_edit.text().lower()
        only_with_profile = self.profile_only_check.isChecked()

        for i in range(self.explorer_list.count()):
            item = self.explorer_list.item(i)
            text = item.text().lower()
            has_profile = item.background().color().name() == "#e8f8f5"

            # Condición de visibilidad
            visible = True
            if search_text and search_text not in text:
                visible = False
            if only_with_profile and not has_profile:
                visible = False

            item.setHidden(not visible)

    def on_explorer_item_double_clicked(self, item):
        """Carga la entidad seleccionada desde el explorador."""
        fid = item.data(Qt.UserRole)
        if not self.current_layer:
            return

        feature = self.current_layer.getFeature(fid)
        if feature.isValid():
            # Traer al frente el panel del editor
            if self.dock_editor:
                self.dock_editor.raise_()

            # Establecer el feature
            self.set_feature(feature, self.current_layer)

            # Resaltar en el mapa
            if iface:
                iface.mapCanvas().flashFeatureIds(self.current_layer, [feature.id()])
                # Opcional: centrar mapa
                # iface.mapCanvas().setExtent(feature.geometry().boundingBox())
                # iface.mapCanvas().refresh()

    def refresh(self):
        """Refresca los horizontes desde el feature (útil después de cambios externos)."""
        if self.current_feature and self.current_layer:
            profile_id, description, self.horizons = HorizonManager.get_profile_data(
                self.current_feature, self.current_layer
            )
            self.profile_id_edit.setText(str(profile_id) if profile_id != -1 else "")
            self.profile_desc_edit.setPlainText(description)
            self.update_ui()

    def export_profile_image(self):
        """Exporta el perfil actual como una imagen."""
        if not self.horizons:
            QMessageBox.warning(self, "Sin datos", "No hay horizontes para exportar.")
            return

        default_name = (
            f"perfil_{self.profile_id_edit.text() or self.current_feature.id()}.png"
        )
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar Perfil como Imagen",
            default_name,
            "Imágenes (*.png *.jpg *.jpeg)",
        )

        if file_path:
            success = self.canvas.save_image(file_path)
            if success:
                QMessageBox.information(
                    self, "Éxito", f"Imagen guardada en: {file_path}"
                )
            else:
                QMessageBox.critical(self, "Error", "No se pudo guardar la imagen.")

    def generate_layer_pdf_report(self):
        """Genera un informe PDF nativo con todos los perfiles de la capa."""
        if not self.current_layer:
            QMessageBox.warning(self, "Error", "Debe seleccionar una capa.")
            return

        default_name = f"informe_perfiles_{self.current_layer.name()}.pdf"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar Informe PDF", default_name, "Documento PDF (*.pdf)"
        )

        if file_path:
            # Guardar el feature actual para restaurarlo después
            original_feature = self.current_feature

            success, message = ReportGenerator.generate_pdf_report(
                self.current_layer, self.canvas, file_path
            )

            # Restaurar el feature original en el panel y canvas
            if original_feature:
                self.set_feature(original_feature, self.current_layer)
            else:
                self.horizons = []
                self.update_ui()

            if success:
                QMessageBox.information(self, "Informe PDF Generado", message)
            else:
                QMessageBox.critical(self, "Error", message)
