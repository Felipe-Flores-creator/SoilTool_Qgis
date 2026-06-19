# -*- coding: utf-8 -*-
import os
import tempfile
from qgis.PyQt.QtCore import Qt, QSize
from qgis.core import (
    QgsProject,
    QgsPrintLayout,
    QgsLayoutItemLabel,
    QgsLayoutItemPicture,
    QgsLayoutItemShape,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsUnitTypes,
    QgsLayoutExporter,
    QgsStyle,
)
from .horizon_manager import HorizonManager


class ReportGenerator:
    @staticmethod
    def generate_pdf_report(layer, canvas_widget, output_path):
        """
        Genera un informe PDF premium utilizando el motor nativo de QGIS.
        Soporta múltiples páginas y diseño mejorado.
        """
        if not layer:
            return False, "No se ha proporcionado una capa válida."

        try:
            from qgis.core import QgsLayoutItemPage
            
            project = QgsProject.instance()
            layout = QgsPrintLayout(project)
            layout.initializeDefaults()
            layout.setName(f"Reporte_{layer.name()}")

            # Configuración base
            margin = 20
            page_width = 210
            page_height = 297
            y_pos = 15
            current_page = 0

            def add_header(layout_obj, current_y, title_text, page_idx):
                # Barra decorativa superior
                rect = QgsLayoutItemShape(layout_obj)
                rect.setShapeType(QgsLayoutItemShape.Rectangle)
                rect.attemptMove(QgsLayoutPoint(0, 0, QgsUnitTypes.LayoutMillimeters), True, False, page_idx)
                rect.attemptResize(
                    QgsLayoutSize(page_width, 25, QgsUnitTypes.LayoutMillimeters)
                )
                rect.setSymbol(
                    QgsStyle.defaultStyle().symbol("simple_fill")
                )
                layout_obj.addLayoutItem(rect)

                # Título en el encabezado
                title = QgsLayoutItemLabel(layout_obj)
                title.setText(title_text)
                f = title.font()
                f.setBold(True)
                title.setFont(f)
                title.setHAlign(Qt.AlignCenter)
                title.setVAlign(Qt.AlignVCenter)
                title.attemptMove(
                    QgsLayoutPoint(margin, 5, QgsUnitTypes.LayoutMillimeters), True, False, page_idx
                )
                title.attemptResize(
                    QgsLayoutSize(
                        page_width - 2 * margin, 15, QgsUnitTypes.LayoutMillimeters
                    )
                )
                layout_obj.addLayoutItem(title)
                return 35

            y_pos = add_header(
                layout, y_pos, f"INFORME TÉCNICO: {layer.name().upper()}", current_page
            )

            features = list(layer.getFeatures())
            profiles_found = 0
            temp_dir = tempfile.mkdtemp()

            for feature in features:
                profile_id, description, horizons = HorizonManager.get_profile_data(
                    feature, layer
                )
                if not horizons:
                    continue

                profiles_found += 1

                # Calcular altura requerida para este perfil (imagen: 70mm, texto: variable)
                altura_imagen = 70
                altura_texto = 22 + 6 + (len(horizons) * 5)
                altura_perfil = 13 + max(altura_imagen, altura_texto) + 15 # 13 por título y línea, 15 por margen inferior
                
                # Verificar espacio en página (si el perfil no cabe, saltar página)
                if y_pos + altura_perfil > 275:
                    page = QgsLayoutItemPage(layout)
                    page.setPageSize("A4", QgsLayoutItemPage.Portrait)
                    layout.pageCollection().addPage(page)
                    current_page += 1
                    y_pos = 15
                    y_pos = add_header(
                        layout, y_pos, f"INFORME TÉCNICO: {layer.name().upper()} (Cont.)", current_page
                    )

                # Título del Perfil con línea inferior
                p_title = QgsLayoutItemLabel(layout)
                p_title.setText(
                    f"PERFIL: {profile_id if profile_id != -1 else f'FID {feature.id()}'}"
                )
                f_p = p_title.font()
                f_p.setBold(True)
                p_title.setFont(f_p)
                p_title.attemptMove(
                    QgsLayoutPoint(margin, y_pos, QgsUnitTypes.LayoutMillimeters), True, False, current_page
                )
                p_title.attemptResize(
                    QgsLayoutSize(
                        page_width - 2 * margin, 8, QgsUnitTypes.LayoutMillimeters
                    )
                )
                layout.addLayoutItem(p_title)

                y_pos += 8
                line = QgsLayoutItemShape(layout)
                line.setShapeType(QgsLayoutItemShape.Rectangle)
                line.attemptMove(
                    QgsLayoutPoint(margin, y_pos, QgsUnitTypes.LayoutMillimeters), True, False, current_page
                )
                line.attemptResize(
                    QgsLayoutSize(
                        page_width - 2 * margin, 0.5, QgsUnitTypes.LayoutMillimeters
                    )
                )
                layout.addLayoutItem(line)

                y_pos += 5
                y_pos_elementos = y_pos

                # Imagen del perfil (Izquierda)
                canvas_widget.set_data(horizons)
                img_path = os.path.join(temp_dir, f"premium_pdf_{feature.id()}.png")
                canvas_widget.save_image(img_path)

                if os.path.exists(img_path):
                    picture = QgsLayoutItemPicture(layout)
                    picture.setPicturePath(img_path)
                    picture.setResizeMode(QgsLayoutItemPicture.Zoom)
                    picture.attemptMove(
                        QgsLayoutPoint(margin, y_pos, QgsUnitTypes.LayoutMillimeters), True, False, current_page
                    )
                    picture.attemptResize(
                        QgsLayoutSize(45, 70, QgsUnitTypes.LayoutMillimeters)
                    )
                    layout.addLayoutItem(picture)

                # Datos y Tabla (Derecha)
                info_x = margin + 50

                desc_label = QgsLayoutItemLabel(layout)
                desc_label.setText(
                    f"Descripción:\n{description or 'Sin descripción técnica registrada.'}"
                )
                desc_label.attemptMove(
                    QgsLayoutPoint(info_x, y_pos, QgsUnitTypes.LayoutMillimeters), True, False, current_page
                )
                desc_label.attemptResize(
                    QgsLayoutSize(
                        page_width - info_x - margin, 20, QgsUnitTypes.LayoutMillimeters
                    )
                )
                layout.addLayoutItem(desc_label)

                y_pos += 22

                # Estructura de "Tabla" para Horizontes
                table_header = QgsLayoutItemLabel(layout)
                table_header.setText("ID | Tope | Base | Textura")
                f_th = table_header.font()
                f_th.setBold(True)
                table_header.setFont(f_th)
                table_header.attemptMove(
                    QgsLayoutPoint(info_x, y_pos, QgsUnitTypes.LayoutMillimeters), True, False, current_page
                )
                table_header.attemptResize(
                    QgsLayoutSize(
                        page_width - info_x - margin, 6, QgsUnitTypes.LayoutMillimeters
                    )
                )
                layout.addLayoutItem(table_header)

                y_pos += 6

                for h in horizons:
                    h_row = QgsLayoutItemLabel(layout)
                    h_row.setText(
                        f"{h.name} | {h.top:4.1f} | {h.bottom:4.1f} | {h.texture}"
                    )
                    h_row.attemptMove(
                        QgsLayoutPoint(info_x, y_pos, QgsUnitTypes.LayoutMillimeters), True, False, current_page
                    )
                    h_row.attemptResize(
                        QgsLayoutSize(
                            page_width - info_x - margin,
                            5,
                            QgsUnitTypes.LayoutMillimeters,
                        )
                    )
                    layout.addLayoutItem(h_row)
                    y_pos += 5

                # Ajustar y_pos para el siguiente perfil (evitar superposición si el texto es corto)
                y_pos_imagen = y_pos_elementos + 70
                y_pos = max(y_pos, y_pos_imagen) + 15  # Espacio entre perfiles

            if profiles_found == 0:
                return False, "No se encontraron entidades con perfiles en esta capa."

            # Pie de página (Fecha) en todas las páginas generadas
            from datetime import datetime
            
            for p_idx in range(current_page + 1):
                footer = QgsLayoutItemLabel(layout)
                footer.setText(
                    f"Generado automáticamente por SoilTool - {datetime.now().strftime('%d/%m/%Y %H:%M')} - Página {p_idx + 1} de {current_page + 1}"
                )
                f_foot = footer.font()
                f_foot.setItalic(True)
                footer.setFont(f_foot)
                footer.setHAlign(Qt.AlignRight)
                footer.attemptMove(
                    QgsLayoutPoint(margin, page_height - 15, QgsUnitTypes.LayoutMillimeters), True, False, p_idx
                )
                footer.attemptResize(
                    QgsLayoutSize(
                        page_width - 2 * margin, 10, QgsUnitTypes.LayoutMillimeters
                    )
                )
                layout.addLayoutItem(footer)

            # Exportación
            exporter = QgsLayoutExporter(layout)
            settings = QgsLayoutExporter.PdfExportSettings()
            result = exporter.exportToPdf(output_path, settings)

            # Limpieza
            for f in os.listdir(temp_dir):
                try:
                    os.remove(os.path.join(temp_dir, f))
                except:
                    pass
            os.rmdir(temp_dir)

            if result == QgsLayoutExporter.Success:
                return True, f"Informe Premium generado con éxito: {output_path}"
            else:
                return False, "Error al exportar el PDF nativo de QGIS."

        except Exception as e:
            import traceback

            return (
                False,
                f"Error crítico en reporte PDF: {str(e)}\n{traceback.format_exc()}",
            )
