"""Physics-based cross-section packing for the Packed harness pattern."""

import math
import site
import sys

import numpy as np

_PYMUNK = None
_PYMUNK_ERROR = None
_CACHE = {}
_FIT_CACHE = {}

SIMULATION_STEPS = 800
SETTLE_STEPS = 300
TIME_STEP = 1.0 / 120.0
INWARD_ACCELERATION = 20.0
SEEDED_INWARD_ACCELERATION = 6.0
SPACE_DAMPING = 0.85
SOLVER_ITERATIONS = 80
COLLISION_SLOP = 0.01
COLLISION_BIAS = 0.95
INITIAL_GAP_MARGIN = 0.5
CACHE_LIMIT = 128


def _load_pymunk():
    global _PYMUNK, _PYMUNK_ERROR
    if _PYMUNK is not None:
        return _PYMUNK
    if _PYMUNK_ERROR is not None:
        return None
    try:
        user_site = site.getusersitepackages()
        if user_site not in sys.path:
            sys.path.insert(0, user_site)
        import pymunk

        _PYMUNK = pymunk
    except Exception as error:
        _PYMUNK_ERROR = error
    return _PYMUNK


def physics_available():
    return _load_pymunk() is not None


def unavailable_message():
    return (
        "Physics engine 'pymunk' is not available. Packed bundling will "
        "fall back to a circular layout and will not work properly. Install "
        "it in the FreeCAD Python environment with: pip install --user pymunk"
    )


def _spiral_positions(diameters, gap):
    count = len(diameters)
    if count == 0:
        return []
    if count == 1:
        return [(0.0, 0.0)]

    radii = np.asarray(diameters, dtype=float) / 2.0
    effective_radii = radii + max(0.0, gap) / 2.0
    start_radius = math.sqrt(float((effective_radii ** 2).sum()) / 0.5)
    indices = np.arange(count) + 0.5
    distances = start_radius * np.sqrt(indices / count)
    angles = indices * math.pi * (3.0 - math.sqrt(5.0))
    positions = np.column_stack(
        [distances * np.cos(angles), distances * np.sin(angles)]
    )

    required_gap = max(0.0, gap) + INITIAL_GAP_MARGIN
    for _ in range(200):
        minimum_gap = None
        for first in range(count):
            for second in range(first + 1, count):
                edge_gap = (
                    math.hypot(
                        positions[second, 0] - positions[first, 0],
                        positions[second, 1] - positions[first, 1],
                    )
                    - radii[first]
                    - radii[second]
                )
                if minimum_gap is None or edge_gap < minimum_gap:
                    minimum_gap = edge_gap
        if minimum_gap is None or minimum_gap >= required_gap:
            break
        positions *= 1.05
    return [tuple(point) for point in positions]


def _relax_separations(positions, radii, iterations=200):
    points = [[float(point[0]), float(point[1])] for point in positions]
    count = len(points)
    for _ in range(iterations):
        moved = False
        for first in range(count):
            for second in range(first + 1, count):
                dx = points[second][0] - points[first][0]
                dy = points[second][1] - points[first][1]
                distance = math.hypot(dx, dy)
                required = radii[first] + radii[second] + 1e-4
                if distance >= required:
                    continue
                if distance < 1e-9:
                    angle = (first * 2.399963229728653 + second) % (
                        2.0 * math.pi
                    )
                    ux = math.cos(angle)
                    uy = math.sin(angle)
                    push = required / 2.0
                else:
                    ux = dx / distance
                    uy = dy / distance
                    push = (required - distance) / 2.0
                points[first][0] -= ux * push
                points[first][1] -= uy * push
                points[second][0] += ux * push
                points[second][1] += uy * push
                moved = True
        if not moved:
            break
    return [(point[0], point[1]) for point in points]


def _resolve_initial_positions(diameters, gap, initial_positions):
    spiral = _spiral_positions(diameters, gap)
    if initial_positions is None:
        return spiral
    resolved = []
    for index, fallback in enumerate(spiral):
        value = initial_positions[index] if index < len(initial_positions) else None
        if value is None:
            resolved.append(fallback)
        else:
            resolved.append((float(value[0]), float(value[1])))
    return resolved


def _packed_positions_uncached(diameters, gap, initial_positions=None):
    pymunk = _load_pymunk()
    if pymunk is None:
        return None

    count = len(diameters)
    if count <= 1:
        return [(0.0, 0.0)] if count else []

    radii = np.asarray(diameters, dtype=float) / 2.0
    effective_radii = radii + max(0.0, gap) / 2.0
    seeded = initial_positions is not None
    initial = _resolve_initial_positions(diameters, gap, initial_positions)
    if seeded:
        points = np.asarray(initial, dtype=float)
        points = points - points.mean(axis=0)
        max_radius = float(np.linalg.norm(points, axis=1).max())
        spiral = np.asarray(_spiral_positions(diameters, gap), dtype=float)
        target_radius = float(np.linalg.norm(spiral, axis=1).max())
        if max_radius > 1e-9 and target_radius > 1e-9:
            points *= target_radius / max_radius
        initial = [tuple(point) for point in points]

    space = pymunk.Space()
    space.gravity = (0.0, 0.0)
    space.damping = SPACE_DAMPING
    space.iterations = SOLVER_ITERATIONS
    space.collision_slop = COLLISION_SLOP
    space.collision_bias = COLLISION_BIAS

    bodies = []
    velocity_generator = np.random.default_rng(17)
    for index, effective_radius in enumerate(effective_radii):
        mass = max(math.pi * float(radii[index]) ** 2, 1e-6)
        effective_radius = max(float(effective_radius), 1e-3)
        moment = pymunk.moment_for_circle(
            mass,
            0.0,
            effective_radius,
        )
        body = pymunk.Body(mass, moment)
        body.position = initial[index]
        body.velocity = (
            (0.0, 0.0)
            if seeded
            else (
                float(velocity_generator.uniform(-0.5, 0.5)),
                float(velocity_generator.uniform(-0.5, 0.5)),
            )
        )
        shape = pymunk.Circle(body, effective_radius)
        shape.friction = 0.4
        shape.elasticity = 0.0
        space.add(body, shape)
        bodies.append(body)

    acceleration = SEEDED_INWARD_ACCELERATION if seeded else INWARD_ACCELERATION
    for _ in range(SIMULATION_STEPS):
        for body in bodies:
            distance = body.position.length
            if distance > 1e-9:
                body.force += (
                    -body.position / distance
                ) * (body.mass * acceleration)
        space.step(TIME_STEP)

    for _ in range(SETTLE_STEPS):
        space.step(TIME_STEP)

    positions = np.array(
        [[body.position.x, body.position.y] for body in bodies],
        dtype=float,
    )
    positions = _relax_separations(positions, [float(radius) for radius in radii])
    positions = np.asarray(positions, dtype=float)
    positions -= positions.mean(axis=0)
    return [tuple(point) for point in positions]


def packed_positions(diameters, gap=0.0, initial_positions=None):
    seed_key = None
    if initial_positions is not None:
        seed_key = tuple(
            None
            if point is None
            else (round(float(point[0]), 6), round(float(point[1]), 6))
            for point in initial_positions
        )
    key = (
        tuple(round(float(diameter), 6) for diameter in diameters),
        round(float(gap), 6),
        seed_key,
    )
    if key in _CACHE:
        return list(_CACHE[key])

    try:
        positions = _packed_positions_uncached(
            diameters,
            gap,
            initial_positions=initial_positions,
        )
    except Exception:
        return None
    if positions is None:
        return None
    radii = [float(diameter) / 2.0 for diameter in diameters]
    center, _radius = _fit_circle(positions, radii)
    shifted = [
        (point[0] - center[0], point[1] - center[1])
        for point in positions
    ]
    if len(_CACHE) >= CACHE_LIMIT:
        _CACHE.clear()
    _CACHE[key] = tuple(shifted)
    return list(shifted)

SAMPLE_SEGMENTS = 72


def _circle_samples(positions, radii):
    angles = np.linspace(0.0, 2.0 * math.pi, SAMPLE_SEGMENTS, endpoint=False)
    cosines = np.cos(angles)
    sines = np.sin(angles)
    points = []
    for position, radius in zip(positions, radii):
        for cosine, sine in zip(cosines, sines):
            points.append(
                (
                    position[0] + radius * cosine,
                    position[1] + radius * sine,
                )
            )
    return points


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


def _fit_circle(positions, radii):
    points = _circle_samples(positions, radii)
    if not points:
        return (0.0, 0.0), 0.0
    return _minimum_enclosing_circle(points)


def fit_radius_for_positions(positions, diameters):
    radii = [float(diameter) / 2.0 for diameter in diameters]
    points = _circle_samples(positions, radii)
    if not points:
        return None
    _center, radius = _minimum_enclosing_circle(points)
    return radius


def packed_fit_radius(diameters):
    key = tuple(round(float(diameter), 6) for diameter in diameters)
    if key in _FIT_CACHE:
        return _FIT_CACHE[key]
    positions = packed_positions(diameters, 0.0)
    if positions is None:
        return None
    radius = fit_radius_for_positions(positions, diameters)
    if radius is None:
        return None
    if len(_FIT_CACHE) >= CACHE_LIMIT:
        _FIT_CACHE.clear()
    _FIT_CACHE[key] = radius
    return radius

