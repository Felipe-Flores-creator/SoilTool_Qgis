import math
import random

from qgis.PyQt.QtCore import QPointF

# Número de puntos de control editables por límite (lápiz del Lienzo 2D).
# Deben coincidir con muestras de la línea: BOUNDARY_STEPS % (SHAPE_POINTS - 1) == 0
SHAPE_POINTS = 9
BOUNDARY_STEPS = 40

# Amplitud del ruido orgánico (px a la escala de referencia) según el tipo de límite
BOUNDARY_AMPLITUDE = {"abrupt": 2, "clear": 5, "gradual": 12, "diffuse": 25}


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
        bottom_offsets=None,
        top_offsets=None,
    ):
        self.name = name
        self.top = top  # Profundidad inicial (cm)
        self.bottom = bottom  # Profundidad final (cm)
        self.color = color  # QColor
        self.texture = texture
        self.boundary_type = boundary_type  # "abrupt", "clear", "gradual", "diffuse"
        # Amplitud del plegamiento (positivo: hacia arriba, negativo: hacia
        # abajo)
        self.folding = folding
        self.fault_type = fault_type  # "none", "normal", "inverse"
        self.fault_displacement = (
            fault_displacement  # Desplazamiento de la falla en píxeles
        )
        self.image_path = image_path
        self.inclination = inclination
        # Forma manual (lápiz): desplazamientos verticales en cm de los
        # SHAPE_POINTS puntos de control del límite inferior. top_offsets sólo
        # se usa en el primer horizonte (superficie del perfil).
        self.bottom_offsets = normalize_offsets(bottom_offsets)
        self.top_offsets = normalize_offsets(top_offsets)

    @property
    def thickness(self):
        """Devuelve el espesor del horizonte."""
        return self.bottom - self.top

    def copy_shape_from(self, other):
        """Copia la forma manual de otro horizonte (al editarlo con el diálogo)."""
        self.bottom_offsets = normalize_offsets(getattr(other, "bottom_offsets", None))
        self.top_offsets = normalize_offsets(getattr(other, "top_offsets", None))


def normalize_offsets(offsets):
    """Devuelve una lista válida de SHAPE_POINTS floats, o None si no hay forma."""
    if not offsets:
        return None
    try:
        values = [float(v) for v in offsets]
    except (TypeError, ValueError):
        return None
    if len(values) != SHAPE_POINTS:
        return None
    if all(abs(v) < 1e-9 for v in values):
        return None
    return values


def interpolate_offsets(offsets, steps=BOUNDARY_STEPS):
    """Interpola los puntos de control (Catmull-Rom) a steps + 1 muestras."""
    if not offsets:
        return [0.0] * (steps + 1)
    n = len(offsets)
    result = []
    for i in range(steps + 1):
        u = (i / steps) * (n - 1)
        k = min(int(u), n - 2)
        t = u - k
        p0 = offsets[max(k - 1, 0)]
        p1 = offsets[k]
        p2 = offsets[k + 1]
        p3 = offsets[min(k + 2, n - 1)]
        t2, t3 = t * t, t * t * t
        result.append(
            0.5
            * (
                2 * p1
                + (-p0 + p2) * t
                + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                + (-p0 + 3 * p1 - 3 * p2 + p3) * t3
            )
        )
    return result


class ProfileGeometry:
    """Generador de geometría orgánica para el perfil con soporte para plegamientos y
    fallas.
    """

    @staticmethod
    def generate_boundary(
        y_coord,
        width,
        amplitude=5,
        steps=BOUNDARY_STEPS,
        folding=0,
        fault_type="none",
        fault_displacement=0,
        inclination=0,
        seed_coord=None,
    ):
        """Genera una línea irregular con plegamiento, fallas e inclinación.

        seed_coord permite fijar la semilla del ruido independientemente de la
        escala (así el mismo perfil se ve igual en pantalla y en el PDF).
        """
        points = []

        # Punto de fractura de la falla con inclinación (dip)
        center_x = width * 0.5

        # Generador local de números aleatorios para evitar cambios en cada
        # redibujado (paintEvent)
        # Usamos la profundidad (y_coord) y round() para evitar inestabilidad
        # por decimales flotantes
        seed_src = y_coord if seed_coord is None else seed_coord
        seed_value = int(round(seed_src * 100)) if seed_src else 42
        rng = random.Random(seed_value)

        # Inclinación: En una falla normal (\), el bloque colgado baja y el
        # plano se inclina hacia él.
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

    @staticmethod
    def compute_boundaries(horizons, width, scale, style_scale=1.0, min_gap=0.5):
        """Calcula todos los límites del perfil (superficie + base de cada horizonte).

        Args:
            horizons: lista de HorizonData ordenada de arriba hacia abajo.
            width: ancho del dibujo (px).
            scale: px por cm de profundidad.
            style_scale: factor para ruido, plegamiento y fallas (1.0 = Lienzo 2D).
            min_gap: separación mínima (px) para que los límites no se crucen.

        Returns:
            Lista de len(horizons) + 1 listas de QPointF (BOUNDARY_STEPS + 1 cada una).
            boundaries[0] es la superficie; boundaries[i + 1] es la base del
            horizonte i.
        """
        if not horizons:
            return []

        def boundary(y_cm, hor, top_of_profile=False):
            amp = BOUNDARY_AMPLITUDE.get(hor.boundary_type, 5) * style_scale
            pts = ProfileGeometry.generate_boundary(
                y_cm * scale,
                width,
                amplitude=amp,
                folding=hor.folding * style_scale,
                fault_type="none" if top_of_profile else hor.fault_type,
                fault_displacement=hor.fault_displacement * style_scale,
                inclination=getattr(hor, "inclination", 0),
                seed_coord=y_cm * 3,  # misma semilla que la escala base (3 px/cm)
            )
            offsets = hor.top_offsets if top_of_profile else hor.bottom_offsets
            if offsets:
                extra = interpolate_offsets(offsets)
                pts = [QPointF(p.x(), p.y() + e * scale) for p, e in zip(pts, extra)]
            return pts

        h0 = horizons[0]
        boundaries = [boundary(0, h0, top_of_profile=True)]
        for hor in horizons:
            boundaries.append(boundary(hor.bottom, hor))

        # Evitar cruces: cada límite queda siempre por debajo del anterior
        for i in range(1, len(boundaries)):
            prev = boundaries[i - 1]
            boundaries[i] = [
                QPointF(p.x(), max(p.y(), q.y() + min_gap))
                for p, q in zip(boundaries[i], prev)
            ]
        return boundaries

    @staticmethod
    def control_indices():
        """Índices de muestra (0..BOUNDARY_STEPS) donde están los puntos de control."""
        step = BOUNDARY_STEPS // (SHAPE_POINTS - 1)
        return [k * step for k in range(SHAPE_POINTS)]
