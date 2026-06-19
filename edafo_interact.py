# -*- coding: utf-8 -*-
import os
from qgis.PyQt.QtWidgets import QAction, QDockWidget, QWidget, QVBoxLayout, QSizePolicy
from qgis.PyQt.QtCore import Qt, pyqtSignal, QTimer
from qgis.PyQt.QtGui import QIcon


class SoilTool:
    def __init__(self, iface):
        self.iface = iface
        self.docks = []
        self.panel = None
        self.canvas = None
        self.action = None
        self.map_tool = None

        # Herramienta de perfil dinámico con Matplotlib
        self.dynamic_profile_dock = None

    def initGui(self):
        # Cargar icono desde el directorio del plugin
        icon_path = os.path.join(os.path.dirname(__file__), "resources", "icon.svg")
        icon = QIcon(icon_path)

        self.action = QAction("Inspeccionar Perfil", self.iface.mainWindow())
        self.action.setIcon(icon)
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle_map_tool)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&SoilTool", self.action)

        # Primer arranque: dejar abierto únicamente el panel "Editor de Perfil"
        # sin modificar el resto del flujo/lógica del plugin.
        if not self.action.isChecked():
            QTimer.singleShot(0, lambda: self.action.setChecked(True))
            QTimer.singleShot(0, lambda: self.toggle_map_tool(True))

    def unload(self):
        # Limpiar la herramienta de mapa
        if self.map_tool:
            self.iface.mapCanvas().unsetMapTool(self.map_tool)
            self.map_tool = None

        # Limpiar los docks
        for dock in self.docks:
            if dock:
                dock.close()
        self.docks = []

        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("&SoilTool", self.action)

    def toggle_map_tool(self, checked):
        # Importaciones relativas para compatibilidad con QGIS
        from .core.map_tool import SoilMapTool

        if not self.map_tool:
            self.map_tool = SoilMapTool(self.iface.mapCanvas())
            self.map_tool.featureSelected.connect(self.process_selected_feature)

        if checked:
            self.iface.mapCanvas().setMapTool(self.map_tool)
            self.show_profile_panels()
            # Sincronizar el estado del botón del panel
            if self.panel and hasattr(self.panel, "select_map_button"):
                self.panel.select_map_button.blockSignals(True)
                self.panel.select_map_button.setChecked(True)
                self.panel.select_map_button.blockSignals(False)
        else:
            self.iface.mapCanvas().unsetMapTool(self.map_tool)
            # Sincronizar el estado del botón del panel
            if self.panel and hasattr(self.panel, "select_map_button"):
                self.panel.select_map_button.blockSignals(True)
                self.panel.select_map_button.setChecked(False)
                self.panel.select_map_button.blockSignals(False)
            # Ocultar los docks cuando se desactiva la herramienta
            for dock in self.docks:
                if dock:
                    dock.hide()

    def show_profile_panels(self):
        from .ui.profile_panel import ProfilePanel

        if not self.docks:
            self.panel = ProfilePanel()
            # Establecer referencia al plugin para que el botón pueda activar la herramienta
            self.panel.plugin_instance = self
            self.panel.horizonsChanged.connect(self.on_horizons_changed)
            self.panel.layer_combo.layerChanged.connect(self.on_layer_changed)

            # 1. Dock del Editor (Controles principales)
            dock_editor = QDockWidget(
                "SoilTool - Editor de Perfil", self.iface.mainWindow()
            )
            dock_editor.setWidget(self.panel)
            dock_editor.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, dock_editor)
            self.docks.append(dock_editor)
            self.panel.dock_editor = dock_editor
            dock_editor.visibilityChanged.connect(self.on_editor_visibility_changed)

            # 2. Dock del Lienzo 2D
            dock_canvas = QDockWidget("SoilTool - Lienzo 2D", self.iface.mainWindow())
            dock_canvas.setWidget(self.panel.canvas_widget)
            dock_canvas.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, dock_canvas)
            self.docks.append(dock_canvas)
            self.panel.dock_canvas = dock_canvas
            dock_canvas.visibilityChanged.connect(
                self.panel.on_canvas_visibility_changed
            )

            # 3. Dock del Explorador
            dock_explorer = QDockWidget(
                "SoilTool - Explorador", self.iface.mainWindow()
            )
            dock_explorer.setWidget(self.panel.explorer_widget)
            dock_explorer.setAllowedAreas(
                Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
            )
            self.iface.addDockWidget(Qt.RightDockWidgetArea, dock_explorer)
            self.docks.append(dock_explorer)
            self.panel.dock_explorer = dock_explorer

            # Instalar filtro de evento personalizado para detectar cambios de pestaña
            from .ui.profile_panel import ExplorerDockEventFilter

            explorer_filter = ExplorerDockEventFilter(self.panel)
            dock_explorer.installEventFilter(explorer_filter)

            dock_explorer.visibilityChanged.connect(
                self.panel.on_explorer_visibility_changed
            )

            # Apilar los docks en forma de pestañas por defecto para no saturar la pantalla
            self._schedule_profile_dock_tabify(dock_editor, dock_canvas, dock_explorer)
            dock_editor.raise_()  # Asegurar que el editor esté al frente inicialmente

            # Dock del Perfil Topográfico Dinámico (Matplotlib)
            self.create_dynamic_profile_dock()
            # Guardar referencia en el panel y conectar visibilidad
            if self.panel:
                self.panel.dock_dem_profile = self.dynamic_profile_dock
                self.dynamic_profile_dock.visibilityChanged.connect(
                    self.panel.on_dem_profile_visibility_changed
                )

        # Mostrar/ocultar docks respetando los checkboxes del panel cuando existan
        for dock in self.docks:
            try:
                # Editor siempre visible
                if dock.widget() == self.panel:
                    dock.setVisible(True)
                    continue

                # Lienzo 2D
                if (
                    hasattr(self.panel, "show_canvas_check")
                    and dock.widget() == self.panel.canvas_widget
                ):
                    dock.setVisible(self.panel.show_canvas_check.isChecked())
                    continue

                # Explorador
                if (
                    hasattr(self.panel, "show_explorer_check")
                    and dock.widget() == self.panel.explorer_widget
                ):
                    dock.setVisible(self.panel.show_explorer_check.isChecked())
                    continue

                # Perfil Topográfico
                if (
                    hasattr(self.panel, "show_dem_profile_check")
                    and dock is self.dynamic_profile_dock
                ):
                    dock.setVisible(self.panel.show_dem_profile_check.isChecked())
                    continue

                # Por defecto mostrar
                dock.setVisible(True)
            except Exception:
                try:
                    dock.setVisible(True)
                except Exception:
                    pass

        if self.map_tool and self.panel:
            self.map_tool.set_target_layer(self.panel.layer_combo.currentLayer())

    def create_dynamic_profile_dock(self):
        """Crea el dock del perfil dinámico con Matplotlib en la parte inferior."""
        if self.dynamic_profile_dock:
            return

        from .ui.dynamic_profile_dock import DynamicProfileDock

        self.dynamic_profile_dock = DynamicProfileDock(
            self.iface.mainWindow(), self.iface
        )
        self.iface.addDockWidget(Qt.BottomDockWidgetArea, self.dynamic_profile_dock)
        self.docks.append(self.dynamic_profile_dock)

    def on_editor_visibility_changed(self, visible):
        """Maneja cambios de visibilidad del dock del editor.
        Cuando el usuario cambia de pestaña (tab), el dock del editor se oculta
        pero NO debemos desactivar la herramienta de mapa ni ocultar los otros docks.
        Solo sincronizamos el estado visual del botón de la barra de herramientas."""
        if not visible:
            if self.action and self.action.isChecked():
                self.action.setChecked(False)
                # Nota: No llamamos a toggle_map_tool(False) aquí porque eso cerraría
                # todos los docks al cambiar de pestaña. El usuario puede desactivar
                # la herramienta explícitamente con el botón o la acción de toolbar.

    def on_layer_changed(self, layer):
        if self.map_tool:
            self.map_tool.set_target_layer(layer)

    def process_selected_feature(self, data):
        feature = data["feature"]
        layer = data["layer"]

        if self.panel:
            # Establecer el feature y capa en el panel
            self.panel.set_feature(feature, layer)

    def on_horizons_changed(self, horizons):
        """
        Slot para manejar cambios en los horizontes.
        Útil para actualizaciones adicionales si son necesarias.
        """
        # Aquí se pueden agregar acciones adicionales cuando cambian los horizontes
        # Por ejemplo, actualizar otras vistas o realizar cálculos
        pass

    def _schedule_profile_dock_tabify(self, dock_editor, dock_canvas, dock_explorer):
        """
        Tabifica los docks del panel usando addTabifiedDockWidget en lugar de
        tabifyDockWidget post-hoc para evitar Access Violation de Qt5 en Windows.

        addTabifiedDockWidget tabifica los docks DURANTE su creación, no después,
        evitando el crash conocido de Qt 5.15.13 en Windows con tabifyDockWidget.
        """
        from qgis.PyQt.QtCore import QTimer

        main_window = self.iface.mainWindow()
        if not main_window:
            return

        # Añadir los docks de forma segura usando addTabifiedDockWidget
        # que es el método diseñado para tabificar en el momento de agregar.
        # Procesamos en orden inverso: el último es el que queda al frente.

        def step1_tabify_canvas():
            try:
                # Tabificar el canvas DENTRO del editor (editor como base)
                main_window.addTabifiedDockWidget(dock_editor, dock_canvas)
            except Exception:
                # Si falla, los docks quedan separados - es aceptable
                pass
            QTimer.singleShot(0, step2_tabify_explorer)

        def step2_tabify_explorer():
            try:
                # Tabificar el explorador DENTRO del canvas (canvas como base)
                main_window.addTabifiedDockWidget(dock_canvas, dock_explorer)
            except Exception:
                pass
            QTimer.singleShot(0, step3_raise_editor)

        def step3_raise_editor():
            try:
                dock_editor.raise_()
            except Exception:
                pass

        QTimer.singleShot(0, step1_tabify_canvas)

    def activate_map_tool(self):
        """
        Activa la herramienta de mapa para seleccionar entidades.
        Este método puede ser llamado desde el panel para activar el seleccionador.
        """
        from .core.map_tool import SoilMapTool

        if not self.map_tool:
            self.map_tool = SoilMapTool(self.iface.mapCanvas())
            self.map_tool.featureSelected.connect(self.process_selected_feature)

        # Asegurar que los paneles estén visibles
        self.show_profile_panels()

        # Activar la herramienta de mapa
        self.iface.mapCanvas().setMapTool(self.map_tool)

        # Actualizar el estado del botón de la barra de herramientas
        if self.action and not self.action.isChecked():
            self.action.setChecked(True)

    def is_map_tool_active(self):
        """
        Verifica si la herramienta de mapa está actualmente activa.
        """
        if self.map_tool:
            return self.iface.mapCanvas().mapTool() == self.map_tool
        return False

    def deactivate_map_tool(self):
        """
        Desactiva la herramienta de mapa.
        """
        if self.action and self.action.isChecked():
            self.action.setChecked(False)
        if self.map_tool:
            self.iface.mapCanvas().unsetMapTool(self.map_tool)
