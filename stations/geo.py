import numpy as np

EARTH_RADIUS_MILES = 3958.8


def haversine_miles(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = (np.radians(v) for v in (lat1, lng1, lat2, lng2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def to_unit_xyz(lat, lng):
    """Points on the unit sphere, shape (n, 3). Chord distance is monotonic in surface distance."""
    lat, lng = np.radians(np.asarray(lat, dtype=float)), np.radians(np.asarray(lng, dtype=float))
    return np.stack([np.cos(lat) * np.cos(lng), np.cos(lat) * np.sin(lng), np.sin(lat)], axis=-1)


def miles_to_chord(miles):
    return 2 * np.sin(miles / (2 * EARTH_RADIUS_MILES))


def chord_to_miles(chord):
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.asarray(chord) / 2)


def densify(coords, step_miles):
    """Insert points so no gap exceeds step_miles.

    coords: sequence of (lat, lng). Returns (points shape (n, 2), cumulative miles shape (n,)).
    """
    pts = np.asarray(coords, dtype=float).reshape(-1, 2)
    if len(pts) < 2:
        return pts, np.zeros(len(pts))
    seg = haversine_miles(pts[:-1, 0], pts[:-1, 1], pts[1:, 0], pts[1:, 1])
    counts = np.maximum(1, np.ceil(seg / step_miles)).astype(int)
    seg_idx = np.repeat(np.arange(len(seg)), counts)
    first_of_segment = np.cumsum(counts) - counts
    frac = (np.arange(counts.sum()) - np.repeat(first_of_segment, counts)) / np.repeat(counts, counts)
    out = pts[seg_idx] + (pts[seg_idx + 1] - pts[seg_idx]) * frac[:, None]
    cum_at_segment_start = np.concatenate([[0.0], np.cumsum(seg)])
    cum = cum_at_segment_start[seg_idx] + seg[seg_idx] * frac
    return np.vstack([out, pts[-1]]), np.append(cum, cum_at_segment_start[-1])
