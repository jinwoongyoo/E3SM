"""Shared helpers for the Aegis Phase 1 scripts (gauges, MOSART cell matching)."""
import numpy as np

# USGS NWIS site metadata (dec_lat_va, dec_long_va, drain_area_va / contrib_drain_area_va
# converted from mi^2 to km^2); see fetch_usgs.py, which re-downloads and records them.
GAUGES = {
    "08114000": dict(river="Brazos", name="Brazos Rv at Richmond, TX", lat=29.5824589, lon=-95.7577275,
                     area_km2=116826.6, contrib_km2=92050.8),
    "08066500": dict(river="Trinity", name="Trinity Rv at Romayor, TX", lat=30.4252067, lon=-94.8507622,
                     area_km2=44511.5, contrib_km2=44511.5),
    "08068000": dict(river="San Jacinto (W Fork)", name="W Fk San Jacinto Rv nr Conroe, TX", lat=30.24465738,
                     lon=-95.4571616, area_km2=2144.5, contrib_km2=2144.5),
    "08069000": dict(river="San Jacinto (Cypress Ck)", name="Cypress Ck nr Westfield, TX", lat=30.0357753,
                     lon=-95.428827, area_km2=738.1, contrib_km2=738.1),
    "08162000": dict(river="Colorado (TX)", name="Colorado Rv at Wharton, TX", lat=29.30913668, lon=-96.1038482,
                     area_km2=108787.3, contrib_km2=79253.6),
}


def match_gauge(lat2d, lon2d, area_km2_2d, glat, glon, garea_km2, win=1, penalty=0.25, valid=None,
                outlet2d=None):
    """Return (j, i, model_area_km2) of the MOSART cell that best matches the gauge.

    Candidates are the cell containing the gauge and its neighbours (+-win cells).
    Score = |ln(model upstream area / USGS drainage area)| + penalty * (Chebyshev
    distance in cells from the containing cell); the lowest score wins. The
    distance penalty keeps a gauge on its own river when a neighbouring main stem
    (e.g. Brazos next to Colorado) happens to have a closer drainage area.
    If outlet2d (terminal outlet index of every cell) is given, candidates must
    drain to the same terminal outlet as the containing cell (same river basin)."""
    lon2d = ((np.asarray(lon2d) + 180.0) % 360.0) - 180.0
    d = (np.asarray(lat2d) - glat) ** 2 + (lon2d - glon) ** 2
    j0, i0 = np.unravel_index(np.argmin(d), d.shape)
    best = None
    for j in range(max(0, j0 - win), min(d.shape[0], j0 + win + 1)):
        for i in range(max(0, i0 - win), min(d.shape[1], i0 + win + 1)):
            a = float(area_km2_2d[j, i])
            if not np.isfinite(a) or a <= 0 or (valid is not None and not valid[j, i]):
                continue
            if outlet2d is not None and outlet2d[j, i] != outlet2d[j0, i0]:
                continue
            score = abs(np.log(a / garea_km2)) + penalty * max(abs(j - j0), abs(i - i0))
            if best is None or score < best[0]:
                best = (score, j, i, a)
    if best is None:
        raise ValueError("no valid cell near gauge")
    return best[1], best[2], best[3]


def terminal_outlets(dn0):
    """dn0: flat 0-based downstream index (-1 = none). Returns the flat index of
    each cell's terminal outlet (itself if it has no downstream)."""
    dn0 = np.asarray(dn0)
    out = np.full(dn0.size, -1, np.int64)
    for k in range(dn0.size):
        if out[k] >= 0:
            continue
        path = [k]
        while dn0[path[-1]] >= 0 and out[path[-1]] < 0:
            path.append(int(dn0[path[-1]]))
        t = out[path[-1]] if out[path[-1]] >= 0 else path[-1]
        out[path] = t
    return out
