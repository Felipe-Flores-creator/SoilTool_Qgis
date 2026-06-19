import random
from qgis.PyQt.QtCore import QPointF
from qgis.PyQt.QtGui import QPolygonF


class HorizonData:
    """Clase para representar un horizonte científico con soporte estratigráfico."""

    def __init__(
        self,
        name,
        top,
        bottom,
        color,
        texture="Loam",
        boundary_type="abrupt",
        folding=0,
        fault_type="none",
        fault_displacement=0,
        image_path=None,
        inclination=0,
    ):
        self.name = name
        self.top = top  # Profundidad inicial (cm)
        self.bottom = bottom  # Profundidad final (cm)
        self.color = color  # QColor
        self.texture = texture
        self.boundary_type = boundary_type  # "abrupt", "clear", "gradual", "diffuse"
        self.folding = folding  # Amplitud del plegamiento (positivo: hacia arriba, negativo: hacia abajo)
        self.fault_type = fault_type  # "none", "normal", "inverse"
        self.fault_displacement = (
            fault_displacement  # Desplazamiento de la falla en píxeles
        )
        self.image_path = image_path
        self.inclination = inclination

    @property
    def thickness(self):
        """Devuelve el espesor del horizonte."""
        return self.bottom - self.top


class ProfileGeometry:
    """Generador de geometría orgánica para el perfil con soporte para plegamientos y fallas."""

    @staticmethod
    def generate_boundary(
        y_coord,
        width,
        amplitude=5,
        steps=40,
        folding=0,
        fault_type="none",
        fault_displacement=0,
        inclination=0,
    ):
        """Genera una línea irregular con plegamiento, fallas geológicas e inclinación."""
        import math

        points = []

        # Punto de fractura de la falla con inclinación (dip)
        center_x = width * 0.5

        # Generador local de números aleatorios para evitar cambios en cada redibujado (paintEvent)
        # Usamos la profundidad (y_coord) y round() para evitar inestabilidad por decimales flotantes
        seed_value = int(round(y_coord * 100)) if y_coord else 42
        rng = random.Random(seed_value)

        # Inclinación: En una falla normal (\), el bloque colgado baja y el plano se inclina hacia él.
        # En una inversa (/), el plano se inclina en dirección opuesta al empuje.
        if fault_type == "normal":
            # Inclinación hacia la derecha (el x aumenta con la profundidad)
            fault_x = center_x + (y_coord * 0.4)
        elif fault_type == "inverse":
            # Inclinación hacia la izquierda (el x disminuye con la profundidad)
            fault_x = center_x - (y_coord * 0.4)
        else:
            fault_x = center_x

        for i in range(steps + 1):
            x = (width / steps) * i

            # 1. Ruido orgánico del límite (estático gracias a la semilla)
            noise = rng.uniform(-amplitude, amplitude)

            # 2. Plegamiento (Uso de función coseno para curva suave)
            nx = (2 * x / width) - 1
            fold_y = -folding * math.cos(nx * math.pi / 2)

            # 3. Falla Geológica Inclinada
            fault_y = 0
            if fault_type != "none":
                if x > fault_x:
                    if fault_type == "normal":
                        fault_y = fault_displacement
                    elif fault_type == "inverse":
                        fault_y = -fault_displacement
                        
            # 4. Inclinación general del horizonte
            tilt_y = 0
            if inclination != 0:
                tilt_y = math.tan(math.radians(inclination)) * (x - center_x)

            points.append(QPointF(x, y_coord + noise + fold_y + fault_y + tilt_y))
        return points

