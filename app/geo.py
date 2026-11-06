from math import asin, cos, radians, sin, sqrt

# Position par défaut du client (Cocody, Abidjan) tant que le GPS du téléphone n'est pas branché
DEFAULT_LAT = 5.3600
DEFAULT_LNG = -3.9900


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """Distance en mètres entre deux points GPS (formule de haversine)."""
    r = 6371000
    p1, p2 = radians(lat1), radians(lat2)
    dp = p2 - p1
    dl = radians(lng2 - lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return int(2 * r * asin(sqrt(a)))