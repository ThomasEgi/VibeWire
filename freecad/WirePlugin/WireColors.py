"""DIN 47100 single-color cable insulation options.

Source: cable_colors_DIN47100.csv (only single-color rows 1-10).
"""

# number, DIN 47100 German name, canonical name, display color
CABLE_COLORS = (
    (1, "weiß", "White", "#f5f5f5"),
    (2, "braun", "Brown", "#7b4a1e"),
    (3, "grün", "Green", "#2e7d32"),
    (4, "gelb", "Yellow", "#f2c200"),
    (5, "grau", "Grey", "#6e6e6e"),
    (6, "rosa", "Pink", "#d81b60"),
    (7, "blau", "Blue", "#1e5aa8"),
    (8, "rot", "Red", "#c62828"),
    (9, "schwarz", "Black", "#1a1a1a"),
    (10, "violett", "Violet", "#6a1b9a"),
)


def names():
    return tuple(name for _number, _german, name, _color in CABLE_COLORS)


def label(name):
    for number, _german, color_name, _color in CABLE_COLORS:
        if color_name == name:
            return f"{number} {color_name}"
    return name


def color_hex(name):
    for _number, _german, color_name, color in CABLE_COLORS:
        if color_name == name:
            return color
    return None


def color_rgb(name):
    value = str(color_hex(name) or "").lstrip("#")
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[index:index + 2], 16) / 255.0 for index in (0, 2, 4))
    except ValueError:
        return None
