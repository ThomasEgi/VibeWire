"""Random-diameter circle packing with pymunk.

The initial condition is a collision-free grid of mixed-diameter cables.
pymunk handles circle-circle contacts while a central inward pressure pulls
the bundle together. This approximates a bundle compressed by an outer wrap
without a deformable boundary constraint.

Run in the FreeCAD GUI console:
    exec(open("/home/mx/opencaudetest/WirePlugin-main/snippet_archive/random_grid_packing_poc.py").read())

Run headless:
    freecadcmd /home/mx/opencaudetest/WirePlugin-main/snippet_archive/random_grid_packing_poc.py
"""

import math
import os
import site
import sys
import time

import numpy as np
from shapely.geometry import MultiPoint

import FreeCAD as App
import Part

user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

import pymunk

V = App.Vector

SNIPPET_DIR = (
    os.path.dirname(os.path.abspath(__file__))
    if "__file__" in globals()
    else "/home/mx/opencaudetest/WirePlugin-main/snippet_archive"
)
BASE_PATH = os.path.join(SNIPPET_DIR, "circle_pattern_poc.py")
base_source = open(BASE_PATH).read().rsplit("\nmain()", 1)[0]
BASE = {"__file__": BASE_PATH, "__name__": "circle_pattern_base"}
exec(compile(base_source, BASE_PATH, "exec"), BASE)

DOC_NAME = "RandomGridPackingPoC"
CABLE_COUNT = 200
BASE_DIAMETER = 3.0
DIAMETER_MIN_FACTOR = 1.0
DIAMETER_MAX_FACTOR = 5.0
RANDOM_SEED = 17
GRID_CLEARANCE = 2.0
GRID_JITTER = 0.5
GRID_JITTER_SEED = 99
PATTERN_SPACING = 10.0

INWARD_ACCELERATION = 20.0
SIMULATION_STEPS = 800
SETTLE_STEPS = 300
TIME_STEP = 1.0 / 120.0
SPACE_DAMPING = 0.9
SOLVER_ITERATIONS = 120
COLLISION_SLOP = 0.01
COLLISION_BIAS = 0.99


def random_diameters(count, seed=RANDOM_SEED):
    generator = np.random.default_rng(seed)
    factors = generator.uniform(
        DIAMETER_MIN_FACTOR,
        DIAMETER_MAX_FACTOR,
        count,
    )
    return BASE_DIAMETER * factors


def grid_seed(radii):
    radius = np.asarray(radii, dtype=float)
    count = len(radius)
    maximum_diameter = 2.0 * float(radius.max())
    spacing = maximum_diameter + GRID_CLEARANCE
    columns = max(1, int(math.ceil(math.sqrt(count))))
    rows = max(1, int(math.ceil(count / columns)))
    positions = np.zeros((count, 2), dtype=float)
    for index in range(count):
        row = index // columns
        column = index % columns
        positions[index, 0] = (column - (columns - 1) / 2.0) * spacing
        positions[index, 1] = ((rows - 1) / 2.0 - row) * spacing
    generator = np.random.default_rng(GRID_JITTER_SEED)
    positions += generator.uniform(
        -GRID_JITTER,
        GRID_JITTER,
        positions.shape,
    )
    return positions, spacing


def build_items(radii):
    palette = list(BASE["EXTRA_COLORS"]) + list(BASE["DEFAULT_COLORS"])
    items = []
    for index, radius in enumerate(radii):
        color = palette[index % len(palette)]
        diameter = 2.0 * radius
        items.append(
            {
                "name": "Cable{:03d}".format(index + 1),
                "label": "Cable {:03d} D{:.2f}".format(index + 1, diameter),
                "color": color,
                "diameter": diameter,
            }
        )
    return items


def pymunk_pack(radii, initial_positions):
    space = pymunk.Space()
    space.gravity = (0.0, 0.0)
    space.damping = SPACE_DAMPING
    space.iterations = SOLVER_ITERATIONS
    space.collision_slop = COLLISION_SLOP
    space.collision_bias = COLLISION_BIAS

    bodies = []
    velocity_generator = np.random.default_rng(GRID_JITTER_SEED + 1)
    for index, radius in enumerate(radii):
        mass = math.pi * radius * radius
        moment = pymunk.moment_for_circle(mass, 0.0, radius)
        body = pymunk.Body(mass, moment)
        body.position = tuple(float(value) for value in initial_positions[index])
        body.velocity = (
            float(velocity_generator.uniform(-1.0, 1.0)),
            float(velocity_generator.uniform(-1.0, 1.0)),
        )
        shape = pymunk.Circle(body, float(radius))
        shape.friction = 0.4
        shape.elasticity = 0.0
        space.add(body, shape)
        bodies.append(body)

    started = time.perf_counter()
    for _ in range(SIMULATION_STEPS):
        for body in bodies:
            distance = body.position.length
            if distance > 1e-9:
                body.force += (
                    -body.position / distance
                ) * (body.mass * INWARD_ACCELERATION)
        space.step(TIME_STEP)

    for _ in range(SETTLE_STEPS):
        space.step(TIME_STEP)

    elapsed = time.perf_counter() - started
    positions = np.array(
        [[body.position.x, body.position.y] for body in bodies],
        dtype=float,
    )
    positions -= positions.mean(axis=0)
    max_speed = max(body.velocity.length for body in bodies)
    return positions, elapsed, max_speed


def _circle_points(center, radius, segments=72):
    angles = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
    return [
        (
            center[0] + radius * math.cos(angle),
            center[1] + radius * math.sin(angle),
        )
        for angle in angles
    ]


def _circumcircle(first, second, third):
    ax, ay = first
    bx, by = second
    cx, cy = third
    determinant = 2.0 * (
        ax * (by - cy)
        + bx * (cy - ay)
        + cx * (ay - by)
    )
    if abs(determinant) < 1e-12:
        pairs = ((first, second), (first, third), (second, third))
        pair = max(
            pairs,
            key=lambda item: math.hypot(
                item[1][0] - item[0][0],
                item[1][1] - item[0][1],
            ),
        )
        center = (
            (pair[0][0] + pair[1][0]) / 2.0,
            (pair[0][1] + pair[1][1]) / 2.0,
        )
        radius = math.hypot(
            pair[1][0] - pair[0][0],
            pair[1][1] - pair[0][1],
        ) / 2.0
        return center, radius

    aa = ax * ax + ay * ay
    bb = bx * bx + by * by
    cc = cx * cx + cy * cy
    ux = (
        aa * (by - cy)
        + bb * (cy - ay)
        + cc * (ay - by)
    ) / determinant
    uy = (
        aa * (cx - bx)
        + bb * (ax - cx)
        + cc * (bx - ax)
    ) / determinant
    center = (ux, uy)
    radius = math.hypot(ax - ux, ay - uy)
    return center, radius


def _minimum_enclosing_circle(points):
    shuffled = list(points)
    order = np.random.default_rng(12345).permutation(len(shuffled))
    shuffled = [shuffled[index] for index in order]
    center = shuffled[0]
    radius = 0.0
    for first_index, first in enumerate(shuffled):
        if math.hypot(
            first[0] - center[0],
            first[1] - center[1],
        ) <= radius + 1e-7:
            continue
        center = first
        radius = 0.0
        for second_index in range(first_index):
            second = shuffled[second_index]
            if math.hypot(
                second[0] - center[0],
                second[1] - center[1],
            ) <= radius + 1e-7:
                continue
            center = (
                (first[0] + second[0]) / 2.0,
                (first[1] + second[1]) / 2.0,
            )
            radius = math.hypot(
                second[0] - first[0],
                second[1] - first[1],
            ) / 2.0
            for third_index in range(second_index):
                third = shuffled[third_index]
                if math.hypot(
                    third[0] - center[0],
                    third[1] - center[1],
                ) <= radius + 1e-7:
                    continue
                center, radius = _circumcircle(first, second, third)
    return center, radius


def fit_wire_envelope(positions, radii):
    sampled = []
    for position, radius in zip(positions, radii):
        sampled.extend(_circle_points(position, radius))
    hull = MultiPoint(sampled).convex_hull
    hull_points = list(hull.exterior.coords)[:-1]
    center, radius = _minimum_enclosing_circle(hull_points)
    return {
        "center": center,
        "radius": radius,
        "hull_points": hull_points,
        "hull_area": hull.area,
    }


def _add_fit_group(document, fit):
    group = document.addObject("App::DocumentObjectGroup", "FitEnvelope")
    group.Label = "Fitted envelope"

    center = fit["center"]
    circle = Part.Circle(
        V(center[0], center[1], 0.0),
        V(0.0, 0.0, 1.0),
        fit["radius"],
    )
    circle_obj = document.addObject("Part::Feature", "FitMEC")
    circle_obj.Label = "Minimum enclosing circle"
    circle_obj.Shape = Part.Wire([circle.toShape()])
    group.addObject(circle_obj)

    marker_size = 3.0
    cross = Part.makeCompound(
        [
            Part.makeLine(
                V(center[0] - marker_size, center[1], 0.0),
                V(center[0] + marker_size, center[1], 0.0),
            ),
            Part.makeLine(
                V(center[0], center[1] - marker_size, 0.0),
                V(center[0], center[1] + marker_size, 0.0),
            ),
        ]
    )
    center_obj = document.addObject("Part::Feature", "FitCenter")
    center_obj.Label = "MEC center"
    center_obj.Shape = cross
    group.addObject(center_obj)

    hull_points = list(fit["hull_points"])
    hull_points.append(hull_points[0])
    hull_obj = document.addObject("Part::Feature", "FitHull")
    hull_obj.Label = "Cable convex hull"
    hull_obj.Shape = Part.makePolygon(
        [V(x, y, 0.0) for x, y in hull_points]
    )
    group.addObject(hull_obj)

    if getattr(App, "GuiUp", False):
        if getattr(circle_obj, "ViewObject", None) is not None:
            circle_obj.ViewObject.LineColor = (0.85, 0.05, 0.55)
            circle_obj.ViewObject.LineWidth = 3.0
        if getattr(center_obj, "ViewObject", None) is not None:
            center_obj.ViewObject.LineColor = (0.9, 0.0, 0.0)
            center_obj.ViewObject.LineWidth = 4.0
        if getattr(hull_obj, "ViewObject", None) is not None:
            hull_obj.ViewObject.LineColor = (0.05, 0.55, 0.25)
            hull_obj.ViewObject.LineWidth = 2.0
    return group


def build_document(
    items,
    radii,
    initial_positions,
    initial_boundary,
    final_positions,
    final_radius,
):
    try:
        existing = App.getDocument(DOC_NAME)
    except NameError:
        existing = None
    if existing is not None:
        App.closeDocument(DOC_NAME)
    document = App.newDocument(DOC_NAME)
    document.Label = "Random Grid Packing PoC"

    initial_group = document.addObject(
        "App::DocumentObjectGroup", "InitialGrid"
    )
    initial_group.Label = "Initial grid ({} cables)".format(len(items))
    final_group = document.addObject(
        "App::DocumentObjectGroup", "PackedSolution"
    )
    final_group.Label = "Packed solution ({} cables)".format(len(items))

    for index, (item, position) in enumerate(
        zip(items, initial_positions)
    ):
        BASE["_add_disk"](
            document,
            initial_group,
            index,
            item,
            tuple(position),
            radii[index],
            name_prefix="Init",
            label_prefix="Init ",
        )

    x_offset = initial_boundary + PATTERN_SPACING + final_radius
    for index, (item, position) in enumerate(zip(items, final_positions)):
        BASE["_add_disk"](
            document,
            final_group,
            index,
            item,
            (float(position[0]) + x_offset, float(position[1])),
            radii[index],
            name_prefix="Packed",
            label_prefix="Packed ",
        )

    BASE["_add_circle_outline"](
        document,
        initial_group,
        "InitBoundary",
        initial_boundary,
        (0.25, 0.25, 0.25),
        1.5,
        center=V(0.0, 0.0, 0.0),
    )
    BASE["_add_circle_outline"](
        document,
        final_group,
        "PackedEnvelope",
        final_radius,
        (0.25, 0.25, 0.25),
        1.5,
        center=V(x_offset, 0.0, 0.0),
    )
    shifted_final = [
        (float(position[0]) + x_offset, float(position[1]))
        for position in final_positions
    ]
    fit = fit_wire_envelope(shifted_final, radii)
    _add_fit_group(document, fit)
    document.recompute()
    return document, fit


def main():
    diameters = random_diameters(CABLE_COUNT)
    radii = diameters / 2.0
    items = build_items(radii)
    initial_positions, spacing = grid_seed(radii)
    initial_boundary = (
        float(np.linalg.norm(initial_positions, axis=1).max())
        + float(radii.max())
        + 0.5
    )
    initial_metrics = BASE["pattern_metrics"](
        initial_positions.tolist(),
        radii,
    )

    final_positions, elapsed, max_speed = pymunk_pack(
        radii,
        initial_positions,
    )
    final_metrics = BASE["pattern_metrics"](
        final_positions.tolist(),
        radii,
    )
    document, fit = build_document(
        items,
        radii,
        initial_positions,
        initial_boundary,
        final_positions,
        final_metrics["bundle_radius"],
    )

    print("Random grid packing (pymunk)")
    print("pymunk version      : {}".format(pymunk.version))
    print("cables              : {}".format(CABLE_COUNT))
    print(
        "diameter range      : {:.2f} .. {:.2f} mm".format(
            diameters.min(),
            diameters.max(),
        )
    )
    print("diameter mean       : {:.2f} mm".format(diameters.mean()))
    print("grid spacing        : {:.2f} mm".format(spacing))
    print("initial boundary    : {:.3f} mm".format(initial_boundary))
    print(
        "initial envelope    : {:.3f} mm".format(
            initial_metrics["envelope_diameter"]
        )
    )
    print(
        "final envelope      : {:.3f} mm".format(
            final_metrics["envelope_diameter"]
        )
    )
    print(
        "final min gap       : {:.6f} mm".format(
            final_metrics["min_edge_gap"]
        )
    )
    print("final max speed     : {:.4f} mm/s".format(max_speed))
    print("simulation duration : {:.3f} s".format(elapsed))
    print(
        "steps               : {}".format(
            SIMULATION_STEPS + SETTLE_STEPS
        )
    )
    print(
        "MEC center          : ({:.3f}, {:.3f}) mm".format(
            fit["center"][0],
            fit["center"][1],
        )
    )
    print("MEC diameter        : {:.3f} mm".format(2.0 * fit["radius"]))
    print("hull vertices       : {}".format(len(fit["hull_points"])))
    print("hull area           : {:.3f} mm^2".format(fit["hull_area"]))

    if getattr(App, "GuiUp", False):
        try:
            import FreeCADGui as Gui

            view = Gui.activeDocument().activeView()
            view.viewTop()
            Gui.SendMsgToActiveView("ViewFit")
            image_path = "/tmp/random_grid_200_pymunk_before_after.png"
            view.saveImage(image_path, 2400, 1200, "White")
            print("image               : {}".format(image_path))

            initial = document.getObject("InitialGrid")
            if getattr(initial, "ViewObject", None) is not None:
                initial.ViewObject.Visibility = False
            envelope = document.getObject("PackedEnvelope")
            if getattr(envelope, "ViewObject", None) is not None:
                envelope.ViewObject.Visibility = False
            Gui.SendMsgToActiveView("ViewFit")
            fitted_path = "/tmp/random_grid_200_fitted.png"
            view.saveImage(fitted_path, 1600, 1600, "White")
            print("fitted image        : {}".format(fitted_path))
        except Exception:
            pass
    return document


main()
