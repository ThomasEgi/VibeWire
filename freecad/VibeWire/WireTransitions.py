"""Geometric transitions for open bundle-segment routing.

The active M3 primitives are:

- point -> segment: S5 (first fixed arc, single bi-arc, fixed fillet) with a
  direct bi-arc fallback below 4R and an entry push below 3R,
- segment -> point: S5 with reversed inputs and a reversed path,
- segment -> segment: common perpendicular plus two 90 degree fillets.

All returned paths are lists of pieces with edge, length, start and end keys.
"""

import math

import FreeCAD as App
import Part

V = App.Vector
EPS = 1e-9


def clamp(value, low=0.0, high=1.0):
    if value < low:
        return low
    if value > high:
        return high
    return value


def unit_vector(vector):
    length = vector.Length
    if length < 1e-12:
        raise ValueError("Cannot normalize a zero vector")
    return V(vector) / length


def closest_points_segments(p1, q1, p2, q2, eps=EPS):
    d1 = q1 - p1
    d2 = q2 - p2
    r = p1 - p2
    a = d1.dot(d1)
    e = d2.dot(d2)
    f = d2.dot(r)

    if a <= eps and e <= eps:
        return p1, p2

    if a <= eps:
        s = 0.0
        t = clamp(f / e)
    else:
        c = d1.dot(r)
        if e <= eps:
            t = 0.0
            s = clamp(-c / a)
        else:
            b = d1.dot(d2)
            denom = a * e - b * b
            if denom > eps * a * e:
                s = clamp((b * f - c * e) / denom)
            else:
                s = 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = clamp(-c / a)
            elif t > 1.0:
                t = 1.0
                s = clamp((b - c) / a)

    return p1 + d1 * s, p2 + d2 * t


def closest_point_on_segment(segment, point):
    start, end = segment
    direction = end - start
    length_sq = direction.dot(direction)
    if length_sq <= EPS * EPS:
        return start
    parameter = clamp((point - start).dot(direction) / length_sq)
    return start + direction * parameter


def raw_segment_param(segment, point):
    start, end = segment
    direction = end - start
    length_sq = direction.dot(direction)
    if length_sq <= EPS * EPS:
        return 0.0
    return (point - start).dot(direction) / length_sq


def arc_from_start_tangent(center, start_point, end_point, start_tangent):
    radius_vector = start_point - center
    normal = unit_vector(radius_vector.cross(start_tangent))
    circle = Part.Circle(center, normal, radius_vector.Length)
    circle.XAxis = unit_vector(radius_vector)
    end_vector = end_point - center
    angle = math.atan2(
        normal.dot(radius_vector.cross(end_vector)),
        radius_vector.dot(end_vector),
    )
    if angle <= 0.0:
        angle += 2.0 * math.pi
    return Part.ArcOfCircle(circle, 0.0, angle).toShape(), angle, normal


def arc_edge(start, end, start_tangent):
    chord = end - start
    chord_length = chord.Length
    if chord_length < 1e-9:
        return None

    cross = chord.cross(start_tangent)
    offset = cross.Length
    if offset < 1e-9 * max(1.0, chord_length):
        return Part.makeLine(start, end)

    normal = unit_vector(start_tangent.cross(cross))
    radius = chord_length * chord_length / (2.0 * offset)
    center = start + normal * radius

    radial_start = start - center
    radial_end = end - center
    axis = unit_vector(radial_start.cross(start_tangent))

    angle = radial_start.getAngle(radial_end)
    if radial_start.cross(radial_end).dot(axis) < 0.0:
        angle = 2.0 * math.pi - angle

    circle = Part.Circle(center, axis, radius)
    circle.XAxis = unit_vector(radial_start)
    return Part.ArcOfCircle(circle, 0.0, angle).toShape()


def biarc_edges(start, start_tangent, end, end_tangent):
    tangent_start = unit_vector(start_tangent)
    tangent_end = unit_vector(end_tangent)

    chord = end - start
    tangent_sum = tangent_start + tangent_end
    chord_length_sq = chord.dot(chord)
    if chord_length_sq < 1e-18:
        return [], start, tangent_start

    dot_product = chord.dot(tangent_sum)
    constant = tangent_sum.dot(tangent_sum) - 4.0
    discriminant = max(
        0.0,
        4.0 * (dot_product * dot_product - chord_length_sq * constant),
    )
    inverse_joint_scale = (
        2.0 * dot_product + math.sqrt(discriminant)
    ) / (2.0 * chord_length_sq)

    if abs(inverse_joint_scale) < 1e-18:
        chord_len = math.sqrt(chord_length_sq)
        arcs = [arc_edge(start, end, tangent_start)]
        return (
            [arc for arc in arcs if arc is not None],
            start + tangent_start * chord_len * 0.5,
            tangent_start,
        )

    try:
        joint_tangent = unit_vector(chord * inverse_joint_scale - tangent_sum)
    except ValueError:
        chord_len = math.sqrt(chord_length_sq)
        arcs = [arc_edge(start, end, tangent_start)]
        return (
            [arc for arc in arcs if arc is not None],
            start + tangent_start * chord_len * 0.5,
            tangent_start,
        )

    joint_scale = 1.0 / inverse_joint_scale
    joint = start + (tangent_start + joint_tangent) * joint_scale
    arcs = [
        arc_edge(start, joint, tangent_start),
        arc_edge(joint, end, joint_tangent),
    ]
    return [arc for arc in arcs if arc is not None], joint, joint_tangent


def solve_first_arc(start_point, start_tangent, aim_point, radius):
    tangent = unit_vector(start_tangent)
    to_aim = aim_point - start_point
    along = to_aim.dot(tangent)
    perpendicular = to_aim - tangent * along
    sideways = perpendicular.Length
    if sideways < 1e-9:
        raise ValueError("Aim point lies on the departure tangent")

    side = perpendicular / sideways
    a = along
    b = radius - sideways
    rho = math.hypot(a, b)
    if radius > rho + 1e-9:
        raise ValueError("Arc radius is too large for the aim point")

    alpha = math.asin(clamp(radius / rho, -1.0, 1.0))
    phi = math.atan2(b, a)

    candidates = []
    for k in range(-2, 3):
        for theta in (
            alpha - phi + 2.0 * math.pi * k,
            math.pi - alpha - phi + 2.0 * math.pi * k,
        ):
            theta = theta % (2.0 * math.pi)
            if theta <= 1e-9 or theta >= math.pi - 1e-9:
                continue
            p1 = (
                start_point
                + tangent * (radius * math.sin(theta))
                + side * (radius * (1.0 - math.cos(theta)))
            )
            direction = unit_vector(
                tangent * math.cos(theta) + side * math.sin(theta)
            )
            if (aim_point - p1).dot(direction) <= 1e-9:
                continue
            center = start_point + side * radius
            arc, angle, normal = arc_from_start_tangent(
                center,
                start_point,
                p1,
                tangent,
            )
            candidates.append(
                {
                    "theta": theta,
                    "angle": angle,
                    "arc": arc,
                    "center": center,
                    "normal": normal,
                    "side": side,
                    "p1": p1,
                    "direction": direction,
                }
            )

    if not candidates:
        raise ValueError("No valid first arc for the given aim point")
    candidates.sort(key=lambda candidate: candidate["theta"])
    return candidates[0]


def solve_s5_point_to_segment(
    start_point,
    start_tangent,
    target_start,
    target_end,
    radius,
):
    tangent = unit_vector(start_tangent)
    target_direction = unit_vector(target_end - target_start)
    target_segment = (target_start, target_end)

    aim = closest_point_on_segment(target_segment, start_point)
    q = aim + target_direction * radius
    minimum_distance = 3.0 * radius

    if (q - start_point).Length < minimum_distance - 1e-9:
        offset = q - start_point
        along = offset.dot(target_direction)
        length_sq = offset.dot(offset)
        discriminant = along * along - length_sq + 9.0 * radius * radius
        if discriminant < 0.0:
            raise ValueError("Cannot solve the 3R start-to-entry clearance")
        shift = -along + math.sqrt(discriminant)
        q = q + target_direction * shift
        if (q - start_point).Length < minimum_distance - 1e-6:
            raise ValueError("S5 could not reach the 3R start-to-entry clearance")

    entry_distance = (q - start_point).Length

    if entry_distance < 4.0 * radius - 1e-9:
        entry_param = raw_segment_param(target_segment, q)
        if entry_param < -1e-9 or entry_param > 1.0 + 1e-9:
            raise ValueError("S5 direct bi-arc entry lies outside the target segment")

        arcs, joint, joint_tangent = biarc_edges(
            start_point,
            tangent,
            q,
            target_direction,
        )
        if len(arcs) != 2:
            raise ValueError("S5 direct bi-arc is degenerate")
        if arcs[0].tangentAt(arcs[0].FirstParameter).dot(tangent) < 1.0 - 1e-6:
            raise ValueError("S5 direct bi-arc does not leave the start tangentially")
        if arcs[-1].tangentAt(arcs[-1].LastParameter).dot(target_direction) < 1.0 - 1e-6:
            raise ValueError("S5 direct bi-arc does not enter the target tangentially")

        pieces = [
            {
                "kind": "arc",
                "name": "direct bi-arc 1",
                "edge": arcs[0],
                "length": arcs[0].Length,
                "start": start_point,
                "end": joint,
            },
            {
                "kind": "arc",
                "name": "direct bi-arc 2",
                "edge": arcs[1],
                "length": arcs[1].Length,
                "start": joint,
                "end": q,
            },
        ]
        radii = [
            piece["edge"].Curve.Radius
            for piece in pieces
            if isinstance(piece["edge"].Curve, Part.Circle)
        ]
        return {
            "mode": "direct_biarc",
            "pieces": pieces,
            "q": q,
            "entry_param": entry_param,
            "transition_length": sum(piece["length"] for piece in pieces),
            "min_radius": min(radii) if radii else None,
            "biarc_radii": [
                arc.Curve.Radius
                for arc in arcs
                if isinstance(arc.Curve, Part.Circle)
            ],
            "start_point": start_point,
            "aim": aim,
            "joint": joint,
            "radius": radius,
        }

    first = solve_first_arc(start_point, tangent, aim, radius)
    p1 = first["p1"]
    direction = first["direction"]

    to_p1 = p1 - aim
    perpendicular = to_p1 - target_direction * to_p1.dot(target_direction)
    if perpendicular.Length < 1e-9:
        perpendicular = target_direction.cross(V(0.0, 0.0, 1.0))
    if perpendicular.Length < 1e-9:
        perpendicular = target_direction.cross(V(0.0, 1.0, 0.0))
    if perpendicular.Length < 1e-9:
        raise ValueError("Cannot determine a target normal")
    perpendicular = unit_vector(perpendicular)

    entry_param = raw_segment_param(target_segment, q)
    if entry_param < -1e-9 or entry_param > 1.0 + 1e-9:
        raise ValueError("S5 entry lies outside the target segment")

    last_aim = q - target_direction * radius
    normal = -perpendicular
    p2 = last_aim - normal * radius
    center = q - normal * radius
    last_arc, last_angle, _ = arc_from_start_tangent(
        center,
        p2,
        q,
        normal,
    )
    if last_arc.tangentAt(last_arc.LastParameter).dot(target_direction) < 1.0 - 1e-6:
        raise ValueError("S5 last arc does not meet the target tangentially")

    arcs, joint, joint_tangent = biarc_edges(p1, direction, p2, normal)
    if len(arcs) != 2:
        raise ValueError("S5 single bi-arc is degenerate")
    if arcs[-1].tangentAt(arcs[-1].LastParameter).dot(normal) < 1.0 - 1e-6:
        raise ValueError("S5 single bi-arc does not meet the last arc tangentially")

    pieces = [
        {
            "kind": "arc",
            "name": "first fixed arc",
            "edge": first["arc"],
            "length": first["arc"].Length,
            "start": start_point,
            "end": p1,
        },
        {
            "kind": "arc",
            "name": "bi-arc 1",
            "edge": arcs[0],
            "length": arcs[0].Length,
            "start": p1,
            "end": joint,
        },
        {
            "kind": "arc",
            "name": "bi-arc 2",
            "edge": arcs[1],
            "length": arcs[1].Length,
            "start": joint,
            "end": p2,
        },
        {
            "kind": "arc",
            "name": "last fixed arc",
            "edge": last_arc,
            "length": last_arc.Length,
            "start": p2,
            "end": q,
        },
    ]

    radii = [
        piece["edge"].Curve.Radius
        for piece in pieces
        if isinstance(piece["edge"].Curve, Part.Circle)
    ]
    return {
        "mode": "fixed_arcs",
        "pieces": pieces,
        "q": q,
        "entry_param": entry_param,
        "transition_length": sum(piece["length"] for piece in pieces),
        "min_radius": min(radii) if radii else None,
        "biarc_radii": [
            arc.Curve.Radius
            for arc in arcs
            if isinstance(arc.Curve, Part.Circle)
        ],
        "normal": normal,
        "p2": p2,
        "joint": joint,
        "start_point": start_point,
        "aim": aim,
        "last_aim": last_aim,
        "first": first,
        "radius": radius,
    }


def reverse_edge(edge):
    if isinstance(edge.Curve, Part.Circle):
        start = edge.valueAt(edge.LastParameter)
        end = edge.valueAt(edge.FirstParameter)
        tangent = -edge.tangentAt(edge.LastParameter)
        reversed_edge, _, _ = arc_from_start_tangent(
            edge.Curve.Center,
            start,
            end,
            tangent,
        )
        return reversed_edge
    return Part.makeLine(
        edge.valueAt(edge.LastParameter),
        edge.valueAt(edge.FirstParameter),
    )


def solve_s5_segment_to_point(
    source_start,
    source_end,
    target_point,
    target_tangent,
    radius,
):
    source_direction = unit_vector(source_end - source_start)
    point_tangent = unit_vector(target_tangent)

    transition = solve_s5_point_to_segment(
        target_point,
        -point_tangent,
        source_end,
        source_start,
        radius,
    )

    forward_pieces = list(transition["pieces"])
    forward_target_run = Part.makeLine(transition["q"], source_start)
    run_added = forward_target_run.Length > EPS
    if run_added:
        forward_pieces.append(
            {
                "kind": "duct",
                "name": "source run",
                "edge": forward_target_run,
                "length": forward_target_run.Length,
                "start": transition["q"],
                "end": source_start,
            }
        )

    reversed_pieces = []
    for piece in reversed(forward_pieces):
        edge = reverse_edge(piece["edge"])
        reversed_pieces.append(
            {
                "kind": piece["kind"],
                "name": piece["name"],
                "edge": edge,
                "length": edge.Length,
                "start": piece["end"],
                "end": piece["start"],
            }
        )

    transition_pieces = reversed_pieces[1:] if run_added else reversed_pieces
    return {
        "pieces": transition_pieces,
        "source_departure": transition["q"],
        "source_direction": source_direction,
        "target_point": target_point,
        "target_tangent": point_tangent,
        "transition": transition,
    }


def solve_segment_to_segment(
    source_start,
    source_end,
    target_start,
    target_end,
    radius,
):
    source_direction = unit_vector(source_end - source_start)
    target_direction = unit_vector(target_end - target_start)

    source_contact, target_contact = closest_points_segments(
        source_start,
        source_end,
        target_start,
        target_end,
    )
    connector = target_contact - source_contact
    connector_length = connector.Length
    if connector_length <= 2.0 * radius + EPS:
        raise ValueError("Common perpendicular is too short for two fillets")
    connector_direction = unit_vector(connector)

    if abs(connector_direction.dot(source_direction)) > 1e-6:
        raise ValueError("Shortest connection is not perpendicular to the source segment")
    if abs(connector_direction.dot(target_direction)) > 1e-6:
        raise ValueError("Shortest connection is not perpendicular to the target segment")

    source_tangent_segment = source_contact - source_direction * radius
    source_tangent_connector = source_contact + connector_direction * radius
    source_center = source_tangent_segment + connector_direction * radius

    target_tangent_connector = target_contact - connector_direction * radius
    target_tangent_segment = target_contact + target_direction * radius
    target_center = target_tangent_connector + target_direction * radius

    source_tangent_param = raw_segment_param(
        (source_start, source_end),
        source_tangent_segment,
    )
    target_tangent_param = raw_segment_param(
        (target_start, target_end),
        target_tangent_segment,
    )
    if source_tangent_param < -1e-9 or source_tangent_param > 1.0 + 1e-9:
        raise ValueError("Source fillet tangent lies outside the source segment")
    if target_tangent_param < -1e-9 or target_tangent_param > 1.0 + 1e-9:
        raise ValueError("Target fillet tangent lies outside the target segment")

    source_arc, source_angle, _ = arc_from_start_tangent(
        source_center,
        source_tangent_segment,
        source_tangent_connector,
        source_direction,
    )
    connector_line = Part.makeLine(source_tangent_connector, target_tangent_connector)
    target_arc, target_angle, _ = arc_from_start_tangent(
        target_center,
        target_tangent_connector,
        target_tangent_segment,
        connector_direction,
    )

    pieces = [
        {
            "kind": "arc",
            "name": "source fillet",
            "edge": source_arc,
            "length": source_arc.Length,
            "start": source_tangent_segment,
            "end": source_tangent_connector,
        },
        {
            "kind": "line",
            "name": "common perpendicular",
            "edge": connector_line,
            "length": connector_line.Length,
            "start": source_tangent_connector,
            "end": target_tangent_connector,
        },
        {
            "kind": "arc",
            "name": "target fillet",
            "edge": target_arc,
            "length": target_arc.Length,
            "start": target_tangent_connector,
            "end": target_tangent_segment,
        },
    ]

    return {
        "pieces": pieces,
        "source_exit": source_tangent_segment,
        "target_entry": target_tangent_segment,
        "source_contact": source_contact,
        "target_contact": target_contact,
        "source_center": source_center,
        "target_center": target_center,
        "source_arc": source_arc,
        "source_angle": source_angle,
        "target_arc": target_arc,
        "target_angle": target_angle,
        "connector_line": connector_line,
        "connector_length": connector_length,
        "connector_direction": connector_direction,
        "transition_length": sum(piece["length"] for piece in pieces),
        "arc_centers": [source_center, target_center],
    }
