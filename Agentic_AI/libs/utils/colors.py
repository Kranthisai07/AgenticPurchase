# libs/utils/colors.py
import numpy as np

# map (R,G,B) to a basic color name
BASIC = {
    "black":   np.array([0,0,0]),
    "white":   np.array([255,255,255]),
    "red":     np.array([220,20,60]),
    "green":   np.array([35,142,35]),
    "blue":    np.array([30,144,255]),
    "yellow":  np.array([255,215,0]),
    "orange":  np.array([255,140,0]),
    "pink":    np.array([255,105,180]),
    "purple":  np.array([138,43,226]),
    "grey":    np.array([128,128,128]),
    "silver":  np.array([192,192,192]),
}

def rgb_to_name(rgb: np.ndarray) -> str:
    diffs = {k: np.linalg.norm(rgb - v) for k, v in BASIC.items()}
    # return the closest named color
    return sorted(diffs.items(), key=lambda x: x[1])[0][0]
