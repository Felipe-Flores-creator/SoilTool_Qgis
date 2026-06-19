# -*- coding: utf-8 -*-
# iface es la interface de QGIS
def classFactory(iface):
    from .edafo_interact import SoilTool
    return SoilTool(iface)
