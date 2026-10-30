"""Pure geometry helpers shared by VibeWire modules."""

import math


def unit_vector(vector, zero="raise", epsilon=1e-9):
    """Return a normalized vector with an explicit zero-vector policy."""
    length = vector.Length
    if length < epsilon:
        if zero == "zero":
            return vector * 0.0
        if zero == "none":
            return None
        raise ValueError("Cannot normalize a zero vector")
    return vector / length


def cross_2d(origin, first, second):
    return (
        (first[0] - origin[0]) * (second[1] - origin[1])
        - (first[1] - origin[1]) * (second[0] - origin[0])
    )


def convex_hull_2d(points):
    """Return the counter-clockwise convex hull of 2D points."""
    unique = sorted(
        set((round(float(x), 9), round(float(y), 9)) for x, y in points)
    )
    if len(unique) <= 1:
        return unique
    lower = []
    for point in unique:
        while (
            len(lower) >= 2
            and cross_2d(lower[-2], lower[-1], point) <= 0.0
        ):
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(unique):
        while (
            len(upper) >= 2
            and cross_2d(upper[-2], upper[-1], point) <= 0.0
        ):
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1]
    area = sum(
        hull[index][0] * hull[(index + 1) % len(hull)][1]
        - hull[(index + 1) % len(hull)][0] * hull[index][1]
        for index in range(len(hull))
    )
    if area < 0.0:
        hull.reverse()
    return hull


def polygon_area_centroid(vertices):
    """Return ``(cx, cy, area)`` for a polygon."""
    count = len(vertices)
    if count < 3:
        if not vertices:
            return 0.0, 0.0, 0.0
        return (
            sum(point[0] for point in vertices) / count,
            sum(point[1] for point in vertices) / count,
            0.0,
        )
    area2 = 0.0
    center_x = 0.0
    center_y = 0.0
    for index in range(count):
        x0, y0 = vertices[index]
        x1, y1 = vertices[(index + 1) % count]
        cross = x0 * y1 - x1 * y0
        area2 += cross
        center_x += (x0 + x1) * cross
        center_y += (y0 + y1) * cross
    area = area2 / 2.0
    if abs(area) < 1e-12:
        return (
            sum(point[0] for point in vertices) / count,
            sum(point[1] for point in vertices) / count,
            0.0,
        )
    return center_x / (6.0 * area), center_y / (6.0 * area), abs(area)


def polygon_centroid(vertices):
    center_x, center_y, _area = polygon_area_centroid(vertices)
    return center_x, center_y


def circle_points(x, y, radius, samples=72, phase=0.0):
    radius = max(0.0, float(radius))
    return [
        (
            x + radius * math.cos(phase + 2.0 * math.pi * index / samples),
            y + radius * math.sin(phase + 2.0 * math.pi * index / samples),
        )
        for index in range(samples)
    ]


def circumscribed_points(x, y, diameter, samples=8):
    if samples <= 0:
        return []
    radius = max(0.0, float(diameter)) / 2.0 / math.cos(math.pi / samples)
    return circle_points(x, y, radius, samples)


def circle_samples(positions, radii, samples=72, margin=0.0):
    points = []
    for (x, y), radius in zip(positions, radii):
        points.extend(
            circle_points(x, y, max(0.0, radius) + margin, samples)
        )
    return points


def circles_hull(
    positions,
    diameters,
    samples=32,
    margin=0.0,
    center_hull=True,
):
    """Return a convex hull of circles and its original centroid."""
    if not positions:
        return None, (0.0, 0.0)
    radii = [max(0.0, float(diameter)) / 2.0 for diameter in diameters]
    points = circle_samples(positions, radii, samples, margin)
    hull = convex_hull_2d(points)
    if len(hull) < 3:
        return None, (0.0, 0.0)
    center_x, center_y, _area = polygon_area_centroid(hull)
    if center_hull:
        hull = [
            (point[0] - center_x, point[1] - center_y)
            for point in hull
        ]
    return hull, (center_x, center_y)


def fit_rigid_2d(source, target):
    """Return ``(cosine, sine, offset_x, offset_y)`` mapping source to target."""
    count = len(source)
    if count == 0:
        return 1.0, 0.0, 0.0, 0.0
    source_x = sum(point[0] for point in source) / count
    source_y = sum(point[1] for point in source) / count
    target_x = sum(point[0] for point in target) / count
    target_y = sum(point[1] for point in target) / count
    dot = 0.0
    cross = 0.0
    for (first_x, first_y), (second_x, second_y) in zip(source, target):
        ax = first_x - source_x
        ay = first_y - source_y
        bx = second_x - target_x
        by = second_y - target_y
        dot += ax * bx + ay * by
        cross += ax * by - ay * bx
    angle = math.atan2(cross, dot)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    offset_x = target_x - (cosine * source_x - sine * source_y)
    offset_y = target_y - (sine * source_x + cosine * source_y)
    return cosine, sine, offset_x, offset_y
