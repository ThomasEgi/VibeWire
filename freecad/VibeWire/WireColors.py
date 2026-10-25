"""Cable insulation colors and primary/tracer quadrant layouts."""

TRACER_NONE = "None"

SINGLE_COLORS = (
    ("Black", "#1a1a1a"),
    ("Brown", "#7b4a1e"),
    ("Red", "#c62828"),
    ("Orange", "#ef6c00"),
    ("Yellow", "#f2c200"),
    ("Green", "#2e7d32"),
    ("Blue", "#1e5aa8"),
    ("Dark Blue", "#0b2e59"),
    ("Violet", "#6a1b9a"),
    ("Grey", "#6e6e6e"),
    ("White", "#f5f5f5"),
    ("Pink", "#d81b60"),
    ("Turquoise", "#009688"),
)
_HEX = dict(SINGLE_COLORS)


def names():
    return tuple(name for name, _color in SINGLE_COLORS)


def color_hex(name):
    return _HEX.get(name)


def color_rgb(name):
    value = str(color_hex(name) or "").lstrip("#")
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[index:index + 2], 16) / 255.0 for index in (0, 2, 4))
    except ValueError:
        return None


def quadrants(primary, tracer):
    if not tracer or tracer == TRACER_NONE or tracer == primary:
        return (primary,) * 4
    return (primary, primary, primary, tracer)


def is_multicolor(primary, tracer):
    return len(set(quadrants(primary, tracer))) > 1


def parse_legacy(name):
    """Split an old combined color name into primary and tracer."""
    if name == "PE":
        return "Green", "Yellow"
    if name in _HEX:
        return name, TRACER_NONE
    parts = str(name or "").split("-")
    if (
        len(parts) >= 2
        and parts[0] in _HEX
        and parts[1] in _HEX
    ):
        return parts[0], parts[1]
    return "Blue", TRACER_NONE
