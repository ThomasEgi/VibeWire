"""Circle-pattern PoC: baseline layout plus shrink-wrap compression packings.

The first baseline is the existing harness arrangement: equal angles on one
circle, with the radius driven by the harness clearance. The other patterns
use a position-based relaxation: a circular boundary shrinks around a
center-seeded bundle, cable contacts are resolved with zero clearance, and the
stable result approximates cables compressed by an outer wrap.

Run in the FreeCAD GUI console:
    exec(open("/home/mx/opencaudetest/WirePlugin-main/snippet_archive/circle_pattern_poc.py").read())

Run headless:
    freecadcmd /home/mx/opencaudetest/WirePlugin-main/snippet_archive/circle_pattern_poc.py
"""

import math
import os
import sys
import time

import numpy as np

import FreeCAD as App
import Part

V = App.Vector

SNIPPET_DIR = (
    os.path.dirname(os.path.abspath(__file__))
    if "__file__" in globals()
    else "/home/mx/opencaudetest/WirePlugin-main/snippet_archive"
)
PROJECT_DIR = os.path.dirname(SNIPPET_DIR)
FREECAD_DIR = os.path.join(PROJECT_DIR, "freecad")
if FREECAD_DIR not in sys.path:
    sys.path.insert(0, FREECAD_DIR)

DOC_NAME = "CirclePatternPoC"
SOURCE_DOC_NAME = "CableWrappingPoC"
DEFAULT_GAP = 0.6
DEFAULT_DIAMETER = 3.0
DEFAULT_COLORS = (
    "Red",
    "Green",
    "Blue",
    "Yellow",
    "Brown",
    "Black",
    "Grey",
)
FALLBACK_RGB = (0.12, 0.35, 0.66)

PACKING_COUNTS = (15, 20, 50)
EXTRA_COLORS = ("Orange", "Pink", "Turquoise", "Violet", "White")
CONTACT_GAP = 0.0
SHRINK_STEPS = 500
SETTLE_STEPS = 300
CONTACT_ITERATIONS = 8
PACKING_JITTER = 0.3
PACKING_SEED = 1
PACKING_START_MARGIN = 2.0
PATTERN_SPACING = 6.0


def _color_rgb(name):
    try:
        from VibeWire.WireColors import color_rgb

        rgb = color_rgb(name)
        if rgb is not None:
            return rgb
    except Exception:
        pass
    return FALLBACK_RGB


def _is_harness(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) in (
        "WireHarness",
        "WireBundle",
    )


def _is_cable(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == "WireCable"


def _find_harness(document):
    if document is None:
        return None
    for obj in document.Objects:
        if _is_harness(obj):
            return obj
    return None


def _source_document():
    candidates = []
    if App.ActiveDocument is not None:
        candidates.append(App.ActiveDocument)
    try:
        named = App.getDocument(SOURCE_DOC_NAME)
    except NameError:
        named = None
    if named is not None and named not in candidates:
        candidates.append(named)
    for document in App.listDocuments().values():
        if document not in candidates:
            candidates.append(document)
    for document in candidates:
        harness = _find_harness(document)
        if harness is not None:
            return document, harness
    return None, None


def read_parameters():
    document, harness = _source_document()
    if harness is None:
        cables = [
            {
                "name": "Cable{:02d}".format(index + 1),
                "label": "Cable {}".format(color),
                "color": color,
                "diameter": DEFAULT_DIAMETER,
            }
            for index, color in enumerate(DEFAULT_COLORS)
        ]
        return {
            "source": None,
            "pattern": "Circular",
            "gap": DEFAULT_GAP,
            "cables": cables,
        }

    order = list(getattr(harness, "CableOrder", []))
    order_index = {name: index for index, name in enumerate(order)}
    cables = [obj for obj in harness.InList if _is_cable(obj)]
    cables.sort(
        key=lambda cable: (
            order_index.get(cable.Name, len(order)),
            cable.Name,
        )
    )
    items = []
    for cable in cables:
        items.append(
            {
                "name": cable.Name,
                "label": getattr(cable, "Label", cable.Name),
                "color": getattr(cable, "CableColor", "Blue"),
                "diameter": max(0.0, float(cable.Diameter.Value)),
            }
        )
    if not items:
        items = [
            {
                "name": "Cable{:02d}".format(index + 1),
                "label": "Cable {}".format(color),
                "color": color,
                "diameter": DEFAULT_DIAMETER,
            }
            for index, color in enumerate(DEFAULT_COLORS)
        ]
    return {
        "source": document.Name if document is not None else None,
        "pattern": getattr(harness, "Pattern", "Circular"),
        "gap": max(0.0, float(harness.Gap.Value)),
        "cables": items,
    }


def cables_for_count(parameters, count):
    items = [dict(item) for item in parameters["cables"][:count]]
    if len(items) >= count:
        return items

    average_diameter = (
        sum(item["diameter"] for item in items) / len(items)
        if items
        else DEFAULT_DIAMETER
    )
    used_colors = {item["color"] for item in items}
    palette = EXTRA_COLORS + DEFAULT_COLORS
    spare_colors = [
        color
        for color in palette
        if color not in used_colors
    ]
    while len(items) < count:
        color = (
            spare_colors.pop(0)
            if spare_colors
            else palette[len(items) % len(palette)]
        )
        items.append(
            {
                "name": "Cable{:02d}".format(len(items) + 1),
                "label": "Cable {}".format(color),
                "color": color,
                "diameter": average_diameter,
            }
        )
    return items


def original_circular_positions(diameters, gap):
    count = len(diameters)
    if count == 0:
        return []
    if count == 1:
        return [(0.0, 0.0)]

    angle_step = 2.0 * math.pi / count
    required = [
        diameters[index] / 2.0
        + gap
        + diameters[(index + 1) % count] / 2.0
        for index in range(count)
    ]
    radius = max(required) / (2.0 * math.sin(math.pi / count))
    return [
        (
            radius * math.cos(index * angle_step),
            radius * math.sin(index * angle_step),
        )
        for index in range(count)
    ]


def pattern_metrics(positions, radii):
    if not positions:
        return {
            "lane_radius": 0.0,
            "bundle_radius": 0.0,
            "envelope_diameter": 0.0,
            "min_edge_gap": 0.0,
        }
    lane_radius = max(math.hypot(x, y) for x, y in positions)
    bundle_radius = max(
        math.hypot(x, y) + radius
        for (x, y), radius in zip(positions, radii)
    )
    min_edge_gap = None
    for first in range(len(positions)):
        for second in range(first + 1, len(positions)):
            x1, y1 = positions[first]
            x2, y2 = positions[second]
            edge_gap = (
                math.hypot(x2 - x1, y2 - y1)
                - radii[first]
                - radii[second]
            )
            if min_edge_gap is None or edge_gap < min_edge_gap:
                min_edge_gap = edge_gap
    return {
        "lane_radius": lane_radius,
        "bundle_radius": bundle_radius,
        "envelope_diameter": 2.0 * bundle_radius,
        "min_edge_gap": min_edge_gap if min_edge_gap is not None else 0.0,
    }


def _center_seed(radii, seed=PACKING_SEED, jitter=PACKING_JITTER):
    radius = np.asarray(radii, dtype=float)
    count = len(radius)
    position = np.zeros((count, 2), dtype=float)
    if count > 1:
        outer_radius = 2.0 * float(radius.max()) + 0.2
        angles = np.arange(count - 1) * 2.0 * math.pi / (count - 1)
        position[1:, 0] = outer_radius * np.cos(angles)
        position[1:, 1] = outer_radius * np.sin(angles)
    generator = np.random.default_rng(seed)
    position += generator.normal(0.0, jitter, position.shape)
    return position


def _target_boundary_radius(radii):
    radius = np.asarray(radii, dtype=float)
    count = len(radius)
    if count == 0:
        return 0.0
    if count == 1:
        return float(radius[0])
    if count == 2:
        return float(radius.sum())
    outer_radius = float(radius.max())
    return outer_radius + outer_radius / math.sin(
        math.pi / (count - 1)
    )


def _center_compression_pack(
    radii,
    gap=CONTACT_GAP,
    shrink_steps=SHRINK_STEPS,
    settle_steps=SETTLE_STEPS,
    iterations=CONTACT_ITERATIONS,
    jitter=PACKING_JITTER,
    seed=PACKING_SEED,
    start_margin=PACKING_START_MARGIN,
):
    """Pack a small bundle by shrinking a boundary around a center-seeded row."""
    radius = np.asarray(radii, dtype=float)
    count = len(radius)
    target = _target_boundary_radius(radius)
    if count <= 1:
        return [tuple(point) for point in _center_seed(radius, seed, jitter)], {
            "method": "center-ring",
            "target": target,
            "boundary": target,
            "steps": 0,
            "max_overlap": 0.0,
        }

    position = _center_seed(radius, seed, jitter)
    start = target + start_margin
    base_radius = radius.mean() if radius.mean() > 1e-9 else 1.0
    mass = np.maximum((radius / base_radius) ** 2, 1e-6)
    inverse_mass = 1.0 / mass
    total_steps = shrink_steps + settle_steps
    boundary = start

    for step in range(total_steps):
        fraction = min(step / max(1, shrink_steps), 1.0)
        boundary = start - (start - target) * fraction
        for _ in range(iterations):
            distances = np.linalg.norm(position, axis=1)
            max_radius = boundary - radius
            outside = distances > max_radius
            if np.any(outside):
                position[outside] *= (
                    max_radius[outside] / distances[outside]
                )[:, None]

            for first in range(count):
                for second in range(first + 1, count):
                    delta = position[second] - position[first]
                    distance = np.linalg.norm(delta)
                    desired = radius[first] + radius[second] + gap
                    if distance < 1e-9:
                        angle = (
                            2.0
                            * math.pi
                            * (first + 1)
                            * (second + 1)
                            / (count * count)
                        )
                        delta = np.array([math.cos(angle), math.sin(angle)])
                        distance = 1e-9
                    if distance < desired:
                        normal = delta / distance
                        correction = normal * (desired - distance)
                        weight_sum = inverse_mass[first] + inverse_mass[second]
                        position[first] -= correction * (
                            inverse_mass[first] / weight_sum
                        )
                        position[second] += correction * (
                            inverse_mass[second] / weight_sum
                        )

    max_overlap = 0.0
    for first in range(count):
        for second in range(first + 1, count):
            distance = np.linalg.norm(position[second] - position[first])
            desired = radius[first] + radius[second] + gap
            max_overlap = max(max_overlap, desired - distance)
    return [tuple(point) for point in position], {
        "method": "center-ring",
        "target": target,
        "boundary": boundary,
        "steps": total_steps,
        "max_overlap": max(max_overlap, 0.0),
    }


def _spiral_seed(radii, phi, seed):
    radius = np.asarray(radii, dtype=float)
    count = len(radius)
    radius_sum = float((radius ** 2).sum())
    start_radius = math.sqrt(radius_sum / max(phi, 1e-6))
    indices = np.arange(count) + 0.5
    distances = start_radius * np.sqrt(indices / max(count, 1))
    angles = indices * math.pi * (3.0 - math.sqrt(5.0))
    position = np.column_stack(
        [distances * np.cos(angles), distances * np.sin(angles)]
    )
    generator = np.random.default_rng(seed)
    position += generator.normal(0.0, 0.05, position.shape)
    return position, start_radius


def _spiral_compression_pack(
    radii,
    gap=CONTACT_GAP,
    phi=0.6,
    shrink_step=0.02,
    settle_steps=200,
    max_steps=3000,
    iterations=12,
    seed=PACKING_SEED,
    tolerance=0.005,
    pressure=1.0,
):
    """Fill a loose seed, then shrink a boundary until contacts jam."""
    radius = np.asarray(radii, dtype=float)
    count = len(radius)
    if count <= 1:
        return [tuple(point) for point in _center_seed(radius, seed)], {
            "method": "spiral-shrink",
            "boundary": _target_boundary_radius(radius),
            "steps": 0,
            "max_overlap": 0.0,
        }

    position, start_radius = _spiral_seed(radius, phi, seed)
    boundary = start_radius + float(radius.max()) + 0.5
    base_radius = radius.mean() if radius.mean() > 1e-9 else 1.0
    mass = np.maximum((radius / base_radius) ** 2, 1e-6)
    inverse_mass = 1.0 / mass
    pair_first, pair_second = np.triu_indices(count, 1)
    desired = radius[pair_first] + radius[pair_second] + gap
    weight_sum = inverse_mass[pair_first] + inverse_mass[pair_second]

    def resolve(current_boundary):
        distances = np.linalg.norm(position, axis=1)
        max_radius = current_boundary - radius
        outside = distances > max_radius
        if np.any(outside):
            position[outside] *= (
                max_radius[outside] / distances[outside]
            )[:, None]

        delta = position[pair_second] - position[pair_first]
        distance = np.linalg.norm(delta, axis=1)
        overlap = desired - distance
        touching = overlap > 0.0
        if np.any(touching):
            normal = delta[touching] / distance[touching, None]
            correction = normal * (
                overlap[touching] / weight_sum[touching]
            )[:, None]
            first = pair_first[touching]
            second = pair_second[touching]
            np.add.at(
                position,
                first,
                -correction * inverse_mass[first, None],
            )
            np.add.at(
                position,
                second,
                correction * inverse_mass[second, None],
            )

    for _ in range(settle_steps):
        for _ in range(iterations):
            resolve(boundary)

    last_good = boundary
    shrink_steps = 0
    max_overlap = 0.0
    for step in range(max_steps):
        boundary -= shrink_step
        if pressure < 1.0:
            position *= pressure
        for _ in range(iterations):
            resolve(boundary)
        delta = position[pair_second] - position[pair_first]
        distance = np.linalg.norm(delta, axis=1)
        max_overlap = max(0.0, float((desired - distance).max()))
        if max_overlap > tolerance:
            boundary += shrink_step
            for _ in range(iterations * 3):
                resolve(boundary)
            break
        last_good = boundary
        shrink_steps += 1

    for _ in range(iterations * 4):
        resolve(last_good)
    delta = position[pair_second] - position[pair_first]
    distance = np.linalg.norm(delta, axis=1)
    max_overlap = max(0.0, float((desired - distance).max()))
    return [tuple(point) for point in position], {
        "method": "spiral-shrink",
        "boundary": last_good,
        "steps": settle_steps + shrink_steps,
        "max_overlap": max_overlap,
    }


def compression_pack_positions(radii, gap=CONTACT_GAP):
    radius = np.asarray(radii, dtype=float)
    if len(radius) <= 8:
        return _center_compression_pack(radius, gap=gap)
    return _spiral_compression_pack(radius, gap=gap)


def _add_disk(
    document,
    group,
    index,
    item,
    position,
    radius,
    name_prefix="Cable",
    label_prefix="",
):
    x, y = position
    center = V(x, y, 0.0)
    circle = Part.Circle(center, V(0.0, 0.0, 1.0), radius)
    face = Part.Face(Part.Wire([circle.toShape()]))
    obj = document.addObject(
        "Part::Feature",
        "{}{:02d}".format(name_prefix, index + 1),
    )
    obj.Label = "{}{:02d} {}".format(label_prefix, index + 1, item["label"])
    obj.Shape = face
    group.addObject(obj)

    if getattr(App, "GuiUp", False) and getattr(obj, "ViewObject", None) is not None:
        rgb = _color_rgb(item["color"])
        obj.ViewObject.ShapeColor = rgb
        obj.ViewObject.LineColor = (0.08, 0.08, 0.08)
        obj.ViewObject.LineWidth = 1.5
        obj.ViewObject.Transparency = 20
    return obj


def _add_circle_outline(
    document,
    group,
    name,
    radius,
    color,
    width,
    center=V(0.0, 0.0, 0.0),
):
    circle = Part.Circle(center, V(0.0, 0.0, 1.0), radius)
    obj = document.addObject("Part::Feature", name)
    obj.Shape = Part.Wire([circle.toShape()])
    group.addObject(obj)
    if getattr(App, "GuiUp", False) and getattr(obj, "ViewObject", None) is not None:
        obj.ViewObject.LineColor = color
        obj.ViewObject.LineWidth = width
    return obj


def _build_pattern_group(
    document,
    group_name,
    group_label,
    cables,
    positions,
    metrics,
    x_offset,
    include_lane,
    name_prefix,
    label_prefix,
):
    group = document.addObject("App::DocumentObjectGroup", group_name)
    group.Label = group_label

    radii = [item["diameter"] / 2.0 for item in cables]
    shifted = [
        (x + x_offset, y)
        for x, y in positions
    ]
    for index, (item, position) in enumerate(zip(cables, shifted)):
        _add_disk(
            document,
            group,
            index,
            item,
            position,
            radii[index],
            name_prefix=name_prefix,
            label_prefix=label_prefix,
        )

    if include_lane:
        _add_circle_outline(
            document,
            group,
            "{}LaneCircle".format(name_prefix),
            metrics["lane_radius"],
            (0.55, 0.55, 0.55),
            1.0,
            center=V(x_offset, 0.0, 0.0),
        )
    _add_circle_outline(
        document,
        group,
        "{}BundleEnvelope".format(name_prefix),
        metrics["bundle_radius"],
        (0.25, 0.25, 0.25),
        1.5,
        center=V(x_offset, 0.0, 0.0),
    )
    return group


def build_document(
    parameters,
    original_positions,
    original_metrics,
    packings,
):
    try:
        existing = App.getDocument(DOC_NAME)
    except NameError:
        existing = None
    if existing is not None:
        App.closeDocument(DOC_NAME)
    document = App.newDocument(DOC_NAME)
    document.Label = "Circle Pattern PoC"

    _build_pattern_group(
        document,
        "OriginalPattern",
        "Harness reference (clearance)",
        parameters["cables"],
        original_positions,
        original_metrics,
        x_offset=0.0,
        include_lane=True,
        name_prefix="Orig",
        label_prefix="Orig ",
    )
    right_edge = original_metrics["bundle_radius"]
    for packing in packings:
        count = packing["count"]
        offset = right_edge + PATTERN_SPACING + packing["metrics"]["bundle_radius"]
        _build_pattern_group(
            document,
            "Packed{}Pattern".format(count),
            "Packed {} (touching)".format(count),
            packing["cables"],
            packing["positions"],
            packing["metrics"],
            x_offset=offset,
            include_lane=False,
            name_prefix="Packed{}".format(count),
            label_prefix="P{} ".format(count),
        )
        right_edge = offset + packing["metrics"]["bundle_radius"]
    document.recompute()
    return document


def _print_metrics(title, metrics):
    if title:
        print(title)
    print("  lane radius          : {:.3f} mm".format(metrics["lane_radius"]))
    print(
        "  envelope             : {:.3f} mm diameter".format(
            metrics["envelope_diameter"]
        )
    )
    print("  minimum edge gap     : {:.3f} mm".format(metrics["min_edge_gap"]))


def _print_positions(cables, positions):
    for item, (x, y) in zip(cables, positions):
        print(
            "  {:>8}  ({:8.3f}, {:8.3f})  r={:.3f}  {}".format(
                item["name"],
                x,
                y,
                item["diameter"] / 2.0,
                item["color"],
            )
        )


def print_report(
    parameters,
    original_positions,
    original_metrics,
    packings,
):
    print("Circle pattern source  : {}".format(parameters["source"] or "defaults"))
    print("Harness pattern        : {}".format(parameters["pattern"]))
    print("Harness clearance gap  : {:.3f} mm".format(parameters["gap"]))
    print("Harness cable count    : {}".format(len(parameters["cables"])))
    print("Packing counts         : {}".format(list(PACKING_COUNTS)))
    print()
    _print_metrics("Harness reference (clearance):", original_metrics)
    print()
    print("Original positions:")
    _print_positions(parameters["cables"], original_positions)
    for packing in packings:
        print()
        print(
            "Compressed packing {} (touching):".format(packing["count"])
        )
        _print_metrics("", packing["metrics"])
        reduction = (
            (
                packing["ring_metrics"]["envelope_diameter"]
                - packing["metrics"]["envelope_diameter"]
            )
            / packing["ring_metrics"]["envelope_diameter"]
            * 100.0
        )
        center_index = min(
            range(len(packing["positions"])),
            key=lambda index: math.hypot(*packing["positions"][index]),
        )
        print(
            "  same-count ring       : {:.3f} mm diameter".format(
                packing["ring_metrics"]["envelope_diameter"]
            )
        )
        print("  reduction vs ring     : {:.2f} %".format(reduction))
        print(
            "  packing method        : {}".format(
                packing["simulation"]["method"]
            )
        )
        print(
            "  final boundary        : {:.3f} mm radius".format(
                packing["simulation"]["boundary"]
            )
        )
        print(
            "  max contact overlap   : {:.6f} mm".format(
                packing["simulation"]["max_overlap"]
            )
        )
        print(
            "  center cable          : {}".format(
                packing["cables"][center_index]["name"]
            )
        )
        print(
            "  relaxation steps      : {}".format(
                packing["simulation"]["steps"]
            )
        )
        print(
            "  simulation duration   : {:.3f} s".format(
                packing["simulation"]["seconds"]
            )
        )
        print("Packing {} positions:".format(packing["count"]))
        _print_positions(packing["cables"], packing["positions"])


def main():
    parameters = read_parameters()
    diameters = [item["diameter"] for item in parameters["cables"]]
    radii = [diameter / 2.0 for diameter in diameters]
    original_positions = original_circular_positions(
        diameters,
        parameters["gap"],
    )
    original_metrics = pattern_metrics(original_positions, radii)

    packings = []
    for count in PACKING_COUNTS:
        cables = cables_for_count(parameters, count)
        count_diameters = [item["diameter"] for item in cables]
        count_radii = [diameter / 2.0 for diameter in count_diameters]
        ring_positions = original_circular_positions(
            count_diameters,
            parameters["gap"],
        )
        ring_metrics = pattern_metrics(ring_positions, count_radii)
        started = time.perf_counter()
        positions, simulation = compression_pack_positions(count_radii)
        simulation["seconds"] = time.perf_counter() - started
        packings.append(
            {
                "count": count,
                "cables": cables,
                "positions": positions,
                "metrics": pattern_metrics(positions, count_radii),
                "ring_metrics": ring_metrics,
                "simulation": simulation,
            }
        )

    print_report(
        parameters,
        original_positions,
        original_metrics,
        packings,
    )
    document = build_document(
        parameters,
        original_positions,
        original_metrics,
        packings,
    )

    print()
    print("Created '{}' with {} objects.".format(document.Name, len(document.Objects)))
    if getattr(App, "GuiUp", False):
        try:
            import FreeCADGui as Gui

            view = Gui.activeDocument().activeView()
            view.viewTop()
            Gui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
    return document


main()
