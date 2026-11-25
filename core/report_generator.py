# -*- coding: utf-8 -*-
"""
Informe PDF profesional de perfiles edafológicos (motor de composiciones de QGIS).

Estructura del documento (A4 vertical):
  1. Portada / resumen: mapa de la capa con los perfiles rotulados, escala, norte,
     tabla resumen y simbología general.
  2. Una ficha por perfil: columna del perfil con simbología litológica, mapa de
     localización, datos de la entidad, tabla de horizontes, observaciones y
     leyenda (materiales y tipos de límite).
"""

import os
import shutil
import tempfile
from datetime import datetime

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsDistanceArea,
    QgsFeature,
    QgsFillSymbol,
    QgsLayoutExporter,
    QgsLayoutItemLabel,
    QgsLayoutItemMap,
    QgsLayoutItemPage,
    QgsLayoutItemPicture,
    QgsLayoutItemScaleBar,
    QgsLayoutItemShape,
    QgsLayoutMeasurement,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsPrintLayout,
    QgsProject,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)

from .horizon_manager import HorizonManager
from .soil_symbology import (
    BOUNDARY_TYPES,
    pattern_key,
    render_boundary_swatch,
    render_column_image,
    render_swatch_image,
)

MM = QgsUnitTypes.LayoutMillimeters
PAGE_W, PAGE_H, MARGIN = 210.0, 297.0, 12.0
DPI = 300
PX_PER_MM = DPI / 25.4

# Paleta sobria en tonos tierra
C_PRIMARY = "#4e342e"
C_ACCENT = "#a1887f"
C_LIGHT = "#efebe9"
C_ROW = "#f8f5f4"
C_TEXT = "#263238"
C_MUTED = "#6d6d6d"
C_LINE = "#bcaaa4"

BOUNDARY_SHORT = {
    "abrupt": "Abrupto",
    "clear": "Claro",
    "gradual": "Gradual",
    "diffuse": "Difuso",
}


def _version():
    try:
        import configparser

        cp = configparser.ConfigParser()
        cp.read(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "metadata.txt"),
            encoding="utf-8",
        )
        return cp["general"].get("version", "")
    except Exception:
        return ""


class _Doc:
    """Pequeño ayudante para colocar elementos en la composición (mm)."""

    def __init__(self, layout, tmp_dir):
        self.layout = layout
        self.tmp = tmp_dir
        self._n_img = 0
        page = layout.pageCollection().page(0)
        page.setPageSize("A4", QgsLayoutItemPage.Portrait)
        self.page = 0

    def new_page(self):
        page = QgsLayoutItemPage(self.layout)
        page.setPageSize("A4", QgsLayoutItemPage.Portrait)
        self.layout.pageCollection().addPage(page)
        self.page = self.layout.pageCollection().pageCount() - 1
        return self.page

    def _place(self, item, x, y, w=None, h=None, page=None):
        self.layout.addLayoutItem(item)
        if w is not None and h is not None:
            item.attemptResize(QgsLayoutSize(w, h, MM))
        item.attemptMove(
            QgsLayoutPoint(x, y, MM), True, False, self.page if page is None else page
        )
        return item

    def rect(self, x, y, w, h, fill, stroke=None, stroke_w=0.2, page=None):
        shape = QgsLayoutItemShape(self.layout)
        shape.setShapeType(QgsLayoutItemShape.Rectangle)
        props = {"color": fill, "outline_style": "no"}
        if stroke:
            props.update(
                {
                    "outline_style": "solid",
                    "outline_color": stroke,
                    "outline_width": str(stroke_w),
                    "outline_width_unit": "MM",
                }
            )
        shape.setSymbol(QgsFillSymbol.createSimple(props))
        return self._place(shape, x, y, w, h, page)

    def text(
        self,
        x,
        y,
        w,
        h,
        text,
        size=8.5,
        bold=False,
        italic=False,
        color=C_TEXT,
        halign="left",
        valign="top",
        page=None,
    ):
        label = QgsLayoutItemLabel(self.layout)
        label.setText(text)
        font = QFont("Arial")
        font.setBold(bold)
        font.setItalic(italic)
        if hasattr(label, "setTextFormat"):
            fmt = QgsTextFormat()
            fmt.setFont(font)
            fmt.setSize(size)
            fmt.setColor(QColor(color))
            label.setTextFormat(fmt)
        else:  # QGIS < 3.24
            font.setPointSizeF(size)
            label.setFont(font)
            label.setFontColor(QColor(color))
        label.setHAlign(
            {
                "left": Qt.AlignmentFlag.AlignLeft,
                "center": Qt.AlignmentFlag.AlignHCenter,
                "right": Qt.AlignmentFlag.AlignRight,
            }[halign]
        )
        label.setVAlign(
            {
                "top": Qt.AlignmentFlag.AlignTop,
                "center": Qt.AlignmentFlag.AlignVCenter,
                "bottom": Qt.AlignmentFlag.AlignBottom,
            }[valign]
        )
        label.setMarginX(0.8)
        label.setMarginY(0.3)
        return self._place(label, x, y, w, h, page)

    def image(self, x, y, w, h, qimage, page=None):
        self._n_img += 1
        path = os.path.join(self.tmp, f"img_{self._n_img}.png")
        qimage.setDotsPerMeterX(int(PX_PER_MM * 1000))
        qimage.setDotsPerMeterY(int(PX_PER_MM * 1000))
        qimage.save(path)
        return self.picture(x, y, w, h, path, page)

    def picture(self, x, y, w, h, path, page=None):
        pic = QgsLayoutItemPicture(self.layout)
        pic.setPicturePath(path)
        pic.setResizeMode(QgsLayoutItemPicture.Zoom)
        return self._place(pic, x, y, w, h, page)


class ReportGenerator:
    @staticmethod
    def generate_pdf_report(layer, canvas_widget, output_path, overrides=None):
        """Genera el informe PDF profesional de todos los perfiles de la capa.

        Args:
            layer: capa vectorial con perfiles.
            canvas_widget: se mantiene por compatibilidad (ya no se usa).
            output_path: ruta del PDF.
            overrides: {fid: (profile_id, description, horizons)} para usar datos
                que aún no se han guardado (p. ej. el perfil abierto en el editor).
        """
        if not layer:
            return False, "No se ha proporcionado una capa válida."

        project = QgsProject.instance()
        tmp_dir = tempfile.mkdtemp(prefix="soiltool_pdf_")
        temp_layers = []
        try:
            profiles = ReportGenerator._collect_profiles(layer, overrides or {})
            if not profiles:
                return False, "No se encontraron entidades con perfiles en esta capa."

            layout = QgsPrintLayout(project)
            layout.initializeDefaults()
            layout.setName(f"SoilTool - {layer.name()}")
            doc = _Doc(layout, tmp_dir)

            labels = ReportGenerator._labels_layer(layer, profiles)
            project.addMapLayer(labels, False)
            temp_layers.append(labels)
            background = ReportGenerator._background_layers(layer)

            ReportGenerator._overview_page(doc, layer, profiles, labels, background)
            for prof in profiles:
                doc.new_page()
                hl = ReportGenerator._highlight_layer(layer, prof["feature"].geometry())
                project.addMapLayer(hl, False)
                temp_layers.append(hl)
                ReportGenerator._profile_page(doc, layer, prof, hl, background)
            ReportGenerator._footers(doc, layer)

            exporter = QgsLayoutExporter(layout)
            settings = QgsLayoutExporter.PdfExportSettings()
            settings.dpi = DPI
            settings.rasterizeWholeImage = False
            result = exporter.exportToPdf(output_path, settings)
            if result == QgsLayoutExporter.Success:
                return (
                    True,
                    f"Informe generado con {len(profiles)} perfiles:\n{output_path}",
                )
            return False, f"Error al exportar el PDF (código {result})."
        except Exception as e:
            import traceback

            return (
                False,
                f"Error crítico en reporte PDF: {str(e)}\n{traceback.format_exc()}",
            )
        finally:
            for tl in temp_layers:
                if project.mapLayer(tl.id()):
                    project.removeMapLayer(tl.id())
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Datos
    # ------------------------------------------------------------------
    @staticmethod
    def _collect_profiles(layer, overrides):
        profiles = []
        for feature in layer.getFeatures():
            if feature.id() in overrides:
                pid, desc, horizons = overrides[feature.id()]
            else:
                pid, desc, horizons = HorizonManager.get_profile_data(feature, layer)
            if not horizons:
                continue
            horizons = sorted(horizons, key=lambda h: h.top)
            label = str(pid) if pid not in (-1, None, "") else f"FID {feature.id()}"
            profiles.append(
                {
                    "feature": feature,
                    "label": label,
                    "description": desc or "",
                    "horizons": horizons,
                }
            )
        profiles.sort(key=lambda p: (len(p["label"]), p["label"]))
        return profiles

    @staticmethod
    def _highlight_layer(layer, geom):
        """Capa temporal con la entidad de la ficha resaltada en rojo."""
        crs = layer.crs()
        gtype = QgsWkbTypes.geometryDisplayString(layer.geometryType())
        if gtype not in ("Point", "Line", "Polygon"):
            gtype = "Polygon"
        highlight = QgsVectorLayer(
            f"{gtype}?crs={crs.authid()}", "soiltool_resaltado", "memory"
        )
        highlight.setCrs(crs)
        if gtype == "Polygon":
            sym = QgsFillSymbol.createSimple(
                {
                    "color": "211,47,47,45",
                    "outline_color": "#c62828",
                    "outline_width": "0.7",
                }
            )
        elif gtype == "Line":
            sym = QgsLineSymbol.createSimple(
                {"line_color": "#c62828", "line_width": "1.0"}
            )
        else:
            sym = QgsMarkerSymbol.createSimple(
                {
                    "name": "circle",
                    "color": "#c62828",
                    "size": "4",
                    "outline_color": "white",
                }
            )
        highlight.setRenderer(QgsSingleSymbolRenderer(sym))
        if geom and not geom.isEmpty():
            f = QgsFeature(highlight.fields())
            f.setGeometry(geom)
            highlight.dataProvider().addFeatures([f])
            highlight.updateExtents()
        return highlight

    @staticmethod
    def _labels_layer(layer, profiles):
        """Capa temporal de puntos con el rótulo de cada perfil (mapa general)."""
        crs = layer.crs()
        labels = QgsVectorLayer(
            f"Point?crs={crs.authid()}&field=label:string(40)",
            "soiltool_rotulos",
            "memory",
        )
        labels.setCrs(crs)
        feats = []
        for prof in profiles:
            geom = prof["feature"].geometry()
            if not geom or geom.isEmpty():
                continue
            f = QgsFeature(labels.fields())
            f.setGeometry(geom.pointOnSurface())
            f["label"] = prof["label"]
            feats.append(f)
        labels.dataProvider().addFeatures(feats)
        labels.updateExtents()
        labels.setRenderer(
            QgsSingleSymbolRenderer(
                QgsMarkerSymbol.createSimple(
                    {
                        "name": "circle",
                        "color": C_PRIMARY,
                        "size": "2.2",
                        "outline_color": "white",
                        "outline_width": "0.3",
                    }
                )
            )
        )
        settings = QgsPalLayerSettings()
        settings.fieldName = "label"
        settings.enabled = True
        fmt = QgsTextFormat()
        font = QFont("Arial")
        font.setBold(True)
        fmt.setFont(font)
        fmt.setSize(8)
        fmt.setColor(QColor(C_PRIMARY))
        buf = QgsTextBufferSettings()
        buf.setEnabled(True)
        buf.setSize(1.0)
        buf.setColor(QColor(255, 255, 255))
        fmt.setBuffer(buf)
        settings.setFormat(fmt)
        if hasattr(Qgis, "LabelPlacement"):
            settings.placement = Qgis.LabelPlacement.AroundPoint
        else:
            settings.placement = QgsPalLayerSettings.AroundPoint
        settings.dist = 1.2
        labels.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        labels.setLabelsEnabled(True)
        return labels

    @staticmethod
    def _background_layers(layer):
        """Capa de suelos + capas visibles del proyecto (mapa base, etc.)."""
        root = QgsProject.instance().layerTreeRoot()
        skip = {layer.id()}
        others = [lyr for lyr in root.checkedLayers() if lyr and lyr.id() not in skip]
        return [layer] + others

    @staticmethod
    def _extent(geoms_rect, map_w, map_h, pad=0.12, min_size=None):
        r = QgsRectangle(geoms_rect)
        if r.isEmpty() or r.width() == 0 or r.height() == 0:
            size = min_size or 100.0
            c = r.center()
            r = QgsRectangle(
                c.x() - size / 2, c.y() - size / 2, c.x() + size / 2, c.y() + size / 2
            )
        r.scale(1 + pad * 2)
        if min_size and r.width() < min_size and r.height() < min_size:
            c = r.center()
            r = QgsRectangle(
                c.x() - min_size / 2,
                c.y() - min_size / 2,
                c.x() + min_size / 2,
                c.y() + min_size / 2,
            )
        return r

    # ------------------------------------------------------------------
    # Elementos de composición
    # ------------------------------------------------------------------
    @staticmethod
    def _header(doc, title, subtitle):
        doc.rect(0, 0, PAGE_W, 24, C_PRIMARY)
        doc.rect(0, 24, PAGE_W, 1.2, C_ACCENT)
        doc.text(MARGIN, 4.5, 150, 9, title, size=15, bold=True, color="#ffffff")
        doc.text(MARGIN, 14, 150, 6, subtitle, size=9, color="#f5efed")
        doc.text(
            PAGE_W - MARGIN - 50,
            6,
            50,
            12,
            f"SoilTool\n{datetime.now().strftime('%d/%m/%Y')}",
            size=8,
            color="#f5efed",
            halign="right",
        )

    @staticmethod
    def _section_title(doc, x, y, w, text):
        doc.text(x, y, w, 5, text.upper(), size=8, bold=True, color=C_PRIMARY)
        doc.rect(x, y + 5, w, 0.35, C_ACCENT)

    @staticmethod
    def _map(doc, x, y, w, h, layers, extent, crs):
        m = QgsLayoutItemMap(doc.layout)
        doc._place(m, x, y, w, h)
        m.setCrs(crs)
        m.setLayers(layers)
        m.setKeepLayerSet(True)
        m.setBackgroundColor(QColor("#fbfaf9"))
        m.setFrameEnabled(True)
        m.setFrameStrokeColor(QColor(C_PRIMARY))
        m.setFrameStrokeWidth(QgsLayoutMeasurement(0.35, MM))
        m.zoomToExtent(extent)

        # Norte
        north = None
        for d in QgsApplication.svgPaths():
            cand = os.path.join(d, "arrows", "NorthArrow_02.svg")
            if os.path.exists(cand):
                north = cand
                break
        if north:
            doc.rect(x + w - 11, y + 1.5, 9.5, 12, "255,255,255,210")
            doc.picture(x + w - 10.5, y + 2, 8.5, 11, north)

        # Escala gráfica
        try:
            sb = QgsLayoutItemScaleBar(doc.layout)
            sb.setStyle("Single Box")
            sb.setLinkedMap(m)
            sb.applyDefaultSize()
            sb.setNumberOfSegments(3)
            sb.setNumberOfSegmentsLeft(0)
            sb.setHeight(1.5)
            if hasattr(sb, "setTextFormat"):
                fmt = QgsTextFormat()
                fmt.setFont(QFont("Arial"))
                fmt.setSize(6.5)
                sb.setTextFormat(fmt)
            sb.setBackgroundEnabled(True)
            sb.setBackgroundColor(QColor(255, 255, 255, 215))
            doc.layout.addLayoutItem(sb)
            sb.attemptMove(QgsLayoutPoint(x + 2, y + h - 10, MM), True, False, doc.page)
            sb.update()
        except Exception:
            pass
        return m

    @staticmethod
    def _table(
        doc, x, y, cols, header, rows, row_h=6.0, max_y=None, font=7.5, on_new_page=None
    ):
        """Tabla simple. cols = [ancho_mm]; las celdas pueden ser texto o
        ('img', QImage). Devuelve la 'y' final (crea páginas si no cabe)."""
        width = sum(cols)
        max_y = max_y or (PAGE_H - 22)

        def draw_header(yy):
            doc.rect(x, yy, width, row_h, C_PRIMARY)
            cx = x
            for w, text in zip(cols, header):
                doc.text(
                    cx,
                    yy,
                    w,
                    row_h,
                    text,
                    size=font,
                    bold=True,
                    color="#ffffff",
                    valign="center",
                )
                cx += w
            return yy + row_h

        y = draw_header(y)
        for i, row in enumerate(rows):
            if y + row_h > max_y:
                doc.new_page()
                y = on_new_page() if on_new_page else 32
                y = draw_header(y)
            doc.rect(
                x, y, width, row_h, C_ROW if i % 2 == 0 else "#ffffff", C_LINE, 0.1
            )
            cx = x
            for w, cell in zip(cols, row):
                if isinstance(cell, tuple) and cell and cell[0] == "img":
                    ih = row_h - 1.6
                    iw = min(w - 2, ih * 1.8)
                    doc.image(cx + (w - iw) / 2, y + 0.8, iw, ih, cell[1])
                else:
                    doc.text(cx, y, w, row_h, str(cell), size=font, valign="center")
                cx += w
            y += row_h
        return y

    @staticmethod
    def _legend(doc, x, y, w, materials, boundaries=True, title="Simbología"):
        """Leyenda de materiales (color + patrón) y tipos de límite."""
        n = len(materials)
        cols = 3
        rows = (n + cols - 1) // cols
        bh = 8 + max(rows, 1) * 7 + (16 if boundaries else 0)
        doc.rect(x, y, w, bh, C_LIGHT, C_LINE, 0.2)
        ReportGenerator._section_title(doc, x + 3, y + 1.5, w - 6, title)
        cy = y + 9
        cw = (w - 6) / cols
        for idx, (texture, color, name) in enumerate(materials):
            cx = x + 3 + (idx % cols) * cw
            yy = cy + (idx // cols) * 7
            sw = render_swatch_image(
                texture, color, 12 * PX_PER_MM, 5 * PX_PER_MM, PX_PER_MM * 0.35
            )
            doc.image(cx, yy, 12, 5, sw)
            doc.text(cx + 13.5, yy - 0.5, cw - 14, 6, name, size=7, valign="center")
        if boundaries:
            by = cy + max(rows, 1) * 7 + 1
            doc.text(
                x + 3,
                by,
                40,
                4,
                "Límites entre horizontes:",
                size=7,
                bold=True,
                color=C_PRIMARY,
            )
            bw = (w - 6) / 4
            for i, (key, label) in enumerate(BOUNDARY_TYPES):
                bx = x + 3 + i * bw
                img = render_boundary_swatch(
                    key, 12 * PX_PER_MM, 4 * PX_PER_MM, PX_PER_MM * 0.35
                )
                doc.image(bx, by + 5.5, 10, 3.5, img)
                doc.text(
                    bx + 11, by + 4.6, bw - 11, 5.5, label, size=6.5, valign="center"
                )
        return y + bh

    @staticmethod
    def _materials(horizons_lists):
        """Materiales distintos (por patrón) con el color más representativo."""
        seen = {}
        for horizons in horizons_lists:
            for h in horizons:
                key, label = pattern_key(h.texture)
                name = h.texture if key == "generic" else label
                if key not in seen:
                    seen[key] = (h.texture, h.color, name)
        return list(seen.values())

    # ------------------------------------------------------------------
    # Páginas
    # ------------------------------------------------------------------
    @staticmethod
    def _overview_page(doc, layer, profiles, labels_layer, background):
        crs = layer.crs()
        ReportGenerator._header(
            doc,
            "INFORME DE PERFILES EDAFOLÓGICOS",
            f"Capa: {layer.name()}",
        )
        total_h = sum(len(p["horizons"]) for p in profiles)
        crs_txt = crs.authid() or crs.description()
        doc.text(
            MARGIN,
            29,
            PAGE_W - 2 * MARGIN,
            10,
            f"<b>{len(profiles)}</b> perfiles · <b>{total_h}</b> horizontes "
            "descritos · "
            f"SRC: {crs_txt} · Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            size=8.5,
            color=C_MUTED,
        ).setMode(QgsLayoutItemLabel.ModeHtml)

        extent = QgsRectangle()
        for p in profiles:
            g = p["feature"].geometry()
            if g and not g.isEmpty():
                extent.combineExtentWith(g.boundingBox())
        map_w, map_h = PAGE_W - 2 * MARGIN, 118
        ext = ReportGenerator._extent(extent, map_w, map_h, pad=0.08)
        ReportGenerator._section_title(
            doc, MARGIN, 38, map_w, "Mapa de ubicación de perfiles"
        )
        ReportGenerator._map(
            doc, MARGIN, 45, map_w, map_h, [labels_layer] + background, ext, crs
        )

        y = 45 + map_h + 6
        ReportGenerator._section_title(doc, MARGIN, y, map_w, "Resumen de perfiles")
        y += 8
        rows = []
        for p in profiles:
            hs = p["horizons"]
            depth = max(h.bottom for h in hs)
            dom = max(hs, key=lambda h: h.bottom - h.top)
            seq = " – ".join(h.name for h in hs)
            rows.append(
                [p["label"], str(len(hs)), f"{depth:g} cm", dom.texture, seq[:60]]
            )

        def cont():
            ReportGenerator._header(
                doc, "RESUMEN DE PERFILES (cont.)", f"Capa: {layer.name()}"
            )
            return 32

        y = ReportGenerator._table(
            doc,
            MARGIN,
            y,
            [28, 20, 24, 44, map_w - 116],
            [
                "Perfil",
                "Horiz.",
                "Prof. total",
                "Material dominante",
                "Secuencia de horizontes",
            ],
            rows,
            row_h=5.8,
            on_new_page=cont,
        )

        materials = ReportGenerator._materials([p["horizons"] for p in profiles])
        rows_leg = (len(materials) + 2) // 3
        need = 8 + rows_leg * 7 + 16
        if y + 5 + need > PAGE_H - 20:
            doc.new_page()
            ReportGenerator._header(doc, "SIMBOLOGÍA GENERAL", f"Capa: {layer.name()}")
            y = 30
        ReportGenerator._legend(
            doc, MARGIN, y + 5, map_w, materials, title="Simbología general"
        )

    @staticmethod
    def _profile_page(doc, layer, prof, highlight, background):
        feature = prof["feature"]
        hs = prof["horizons"]
        crs = layer.crs()
        ReportGenerator._header(
            doc,
            f"PERFIL EDAFOLÓGICO  {prof['label']}",
            f"Capa: {layer.name()}  ·  Entidad FID {feature.id()}",
        )

        # --- Columna del perfil (izquierda) ---
        col_x, col_y, col_w, col_h = MARGIN, 36, 62, 188
        ReportGenerator._section_title(doc, col_x, 29, col_w, "Columna del perfil")
        img = render_column_image(
            hs,
            col_w * PX_PER_MM,
            col_h * PX_PER_MM,
            unit=PX_PER_MM * 0.28,
            ruler_width=PX_PER_MM * 9,
            font_px=PX_PER_MM * 2.5,
        )
        doc.image(col_x, col_y, col_w, col_h, img)
        doc.text(
            col_x,
            col_y + col_h + 0.5,
            col_w,
            4,
            "Profundidad (cm)",
            size=6.5,
            italic=True,
            color=C_MUTED,
        )

        # --- Localización (derecha) ---
        rx, rw = 82.0, PAGE_W - MARGIN - 82.0
        ReportGenerator._section_title(doc, rx, 29, rw, "Localización")
        geom = feature.geometry()
        if geom and not geom.isEmpty():
            min_size = 0.002 if crs.isGeographic() else 200.0
            ext = ReportGenerator._extent(
                geom.boundingBox(), rw, 68, pad=0.6, min_size=min_size
            )
        else:
            ext = layer.extent()
        ReportGenerator._map(doc, rx, 36, rw, 68, [highlight] + background, ext, crs)

        # --- Datos de la entidad ---
        y = 108
        ReportGenerator._section_title(doc, rx, y, rw, "Datos del perfil")
        y += 7
        depth = max(h.bottom for h in hs)
        info = [("Perfil", prof["label"]), ("Entidad (FID)", str(feature.id()))]
        if geom and not geom.isEmpty():
            pt = geom.pointOnSurface().asPoint()
            dec = 6 if crs.isGeographic() else 2
            info.append(("Coordenadas (X, Y)", f"{pt.x():.{dec}f}, {pt.y():.{dec}f}"))
            area = ReportGenerator._area(geom, crs)
            if area:
                info.append(("Superficie", area))
        info.append(("SRC", crs.authid() or crs.description()))
        info.append(("Profundidad total", f"{depth:g} cm  ·  {len(hs)} horizontes"))
        for i, (k, v) in enumerate(info):
            doc.rect(rx, y, rw, 5.2, C_ROW if i % 2 == 0 else "#ffffff", C_LINE, 0.1)
            doc.text(
                rx, y, 36, 5.2, k, size=7.2, bold=True, color=C_PRIMARY, valign="center"
            )
            doc.text(rx + 36, y, rw - 36, 5.2, v, size=7.2, valign="center")
            y += 5.2

        # --- Tabla de horizontes ---
        y += 5
        ReportGenerator._section_title(doc, rx, y, rw, "Descripción de horizontes")
        y += 7
        rows = []
        for h in hs:
            sw = render_swatch_image(
                h.texture, h.color, 18 * PX_PER_MM, 10 * PX_PER_MM, PX_PER_MM * 0.35
            )
            rows.append(
                [
                    ("img", sw),
                    h.name,
                    f"{h.top:g} – {h.bottom:g}",
                    f"{h.bottom - h.top:g}",
                    f"{h.texture}\n{h.color.name().upper()}",
                    BOUNDARY_SHORT.get(h.boundary_type, h.boundary_type),
                ]
            )
        legend_h = 8 + ((len(ReportGenerator._materials([hs])) + 2) // 3) * 7 + 16
        bottom_limit = PAGE_H - 20 - legend_h - 4
        row_h = 7.0
        avail = bottom_limit - y - row_h - 18
        if len(rows) * row_h > avail:
            row_h = max(5.0, avail / max(len(rows), 1))

        def cont():
            ReportGenerator._header(
                doc, f"PERFIL {prof['label']} (cont.)", f"Capa: {layer.name()}"
            )
            return 32

        y = ReportGenerator._table(
            doc,
            rx,
            y,
            [14, 20, 20, 14, rw - 84, 16],
            [
                "Símbolo",
                "Horizonte",
                "Prof. (cm)",
                "Esp.",
                "Material / color",
                "Límite",
            ],
            rows,
            row_h=row_h,
            font=6.8,
            max_y=PAGE_H - 22,
            on_new_page=cont,
        )

        # --- Observaciones ---
        if prof["description"]:
            y += 4
            ReportGenerator._section_title(doc, rx, y, rw, "Observaciones")
            obs_h = max(10.0, min(30.0, bottom_limit - y - 7))
            doc.text(rx, y + 7, rw, obs_h, prof["description"], size=7.5)
            y += 7 + obs_h

        # --- Leyenda ---
        ly = max(y + 4, col_y + col_h + 6)
        if ly + legend_h > PAGE_H - 18:
            doc.new_page()
            ReportGenerator._header(
                doc, f"PERFIL {prof['label']} (cont.)", f"Capa: {layer.name()}"
            )
            ly = 32
        ReportGenerator._legend(
            doc, MARGIN, ly, PAGE_W - 2 * MARGIN, ReportGenerator._materials([hs])
        )

    @staticmethod
    def _area(geom, crs):
        try:
            if "Polygon" not in QgsWkbTypes.geometryDisplayString(geom.type()):
                return None
            da = QgsDistanceArea()
            project = QgsProject.instance()
            da.setSourceCrs(crs, project.transformContext())
            ellipsoid = project.ellipsoid()
            if not ellipsoid or ellipsoid.upper() == "NONE":
                ellipsoid = "EPSG:7030"  # WGS84
            da.setEllipsoid(ellipsoid)
            a = da.measureArea(geom)
            if a <= 0:
                return None
            if a >= 10000:
                return f"{a / 10000:,.2f} ha".replace(",", " ")
            return f"{a:,.0f} m²".replace(",", " ")
        except Exception:
            return None

    @staticmethod
    def _footers(doc, layer):
        n = doc.layout.pageCollection().pageCount()
        ver = _version()
        for p in range(n):
            doc.rect(MARGIN, PAGE_H - 13, PAGE_W - 2 * MARGIN, 0.3, C_ACCENT, page=p)
            doc.text(
                MARGIN,
                PAGE_H - 12,
                120,
                6,
                f"SoilTool {ver} · Informe de perfiles edafológicos · {layer.name()}",
                size=7,
                color=C_MUTED,
                page=p,
            )
            doc.text(
                PAGE_W - MARGIN - 40,
                PAGE_H - 12,
                40,
                6,
                f"Página {p + 1} de {n}",
                size=7,
                color=C_MUTED,
                halign="right",
                page=p,
            )
