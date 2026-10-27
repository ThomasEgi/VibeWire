"""M3 open-duct test: shortest path through ordered duct centerlines.

Scenario
--------
A T junction in the z=0 plane (left arm, right arm, vertical stem) and a
segment rising at 45 degrees in two planes above it. Its direction is
(1, 1, 1), so it is not coplanar with the base wires. The route order is
fixed to left -> stem -> angled. Between consecutive ducts the shortest
connecting line between the duct centerlines is computed; its endpoints
become the exit of the current duct and the entry of the next one. The
wire then travels along each duct between its entry and exit point. The
stem -> angled transition is overridden to leave at the stem end and enter
the angled duct at its closest point from that end.

The script compares two smooth transition strategies from that forced stem
end into the angled duct:

1. arc -> line -> arc: a custom first-arc solver aims the first arc at the
   target, then a straight line and a fillet enter the target.
2. bi-arc -> shifted direct line -> simple arc: keep the original direct-line
   direction, shift that line along the target, use the standard bi-arc
   solver for the stem exit, and a simple fillet for the target entry.
3. alignment arc -> arc -> line -> arc: one fixed-radius arc turns the stem
   tangent to a tangent parallel to the target, then the arc-line-arc solver
   enters the target with the same radius.
4. alignment arc -> 90 degree arc -> perpendicular line -> 90 degree arc:
   the same alignment arc, then a perpendicular straight section and a
   quarter-circle fillet into the target.

All strategies use ARC_RADIUS_FACTOR * cable diameter for the controlled
arcs. The bi-arc radii are free but are checked against that minimum. The
straight line in the second strategy keeps the original direct-line
direction and can be moved along the target segment.

The right arm is the unused T branch. It is displayed but not routed.

Run in the FreeCAD GUI console:
    exec(open("/home/mx/opencaudetest/WirePlugin-main/snippet_archive/m3_open_duct_shortest_path.py").read())

Run headless:
    freecadcmd /home/mx/opencaudetest/WirePlugin-main/snippet_archive/m3_open_duct_shortest_path.py
"""

import math

import FreeCAD as App
import Part

V = App.Vector

DOC_NAME = "M3_OpenDuctTest"
EPS = 1e-9

CABLE_DIAMETER = 4.0
DUCT_RADIUS = 1.2
MARKER_RADIUS = 2.5

ARC_RADIUS_FACTOR = 4.0
ARC_RADIUS = ARC_RADIUS_FACTOR * CABLE_DIAMETER
ARC_ENTRY_PARAM = 0.7

BIARC_LINE_ARC_ENTRY_PARAM = 0.9
BIARC_LINE_ARC_STRAIGHT_LENGTH = 20.0

ALIGN_ARC_ENTRY_PARAM = 0.7

SEGMENTS = {
    "left": (V(-80.0, 0.0, 0.0), V(0.0, 0.0, 0.0)),
    "right": (V(0.0, 0.0, 0.0), V(80.0, 0.0, 0.0)),
    "stem": (V(0.0, 0.0, 0.0), V(0.0, 80.0, 0.0)),
    "angled": (V(-40.0, 0.0, 20.0), V(40.0, 80.0, 100.0)),
}

ROUTE = ["left", "stem", "angled"]
FORCED_EXITS = {
    ("stem", "angled"): "end",
}
EXTRA_ROUTES = [
    ["left", "right", "angled"],
    ["angled", "stem", "right"],
]

EXPECTED_BRIDGE = 20.0 * math.sqrt(114.0) / 3.0
EXPECTED_ANGLED_RUN = 140.0 * math.sqrt(3.0) / 3.0
EXPECTED_TOTAL = 80.0 + 80.0 + EXPECTED_BRIDGE + EXPECTED_ANGLED_RUN


def clamp(value, low=0.0, high=1.0):
    if value < low:
        return low
    if value > high:
        return high
    return value


def closest_points_segments(p1, q1, p2, q2, eps=EPS):
    """Return the closest pair of points on two finite 3D segments."""
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


def segment_param(segment, point):
    start, end = segment
    direction = end - start
    length_sq = direction.dot(direction)
    if length_sq <= EPS * EPS:
        return 0.0
    return clamp((point - start).dot(direction) / length_sq)


def raw_segment_param(segment, point):
    start, end = segment
    direction = end - start
    length_sq = direction.dot(direction)
    if length_sq <= EPS * EPS:
        return 0.0
    return (point - start).dot(direction) / length_sq


def unit_vector(vector):
    length = vector.Length
    if length < 1e-12:
        raise ValueError("Cannot normalize a zero vector")
    return V(vector) / length


def param_kind(param):
    if param <= 1e-6:
        return "start endpoint"
    if param >= 1.0 - 1e-6:
        return "end endpoint"
    return "interior"


def closest_point_on_segment(segment, point):
    start, end = segment
    return start + (end - start) * segment_param(segment, point)


def forced_exit_point(segment, policy):
    if policy == "start":
        return segment[0]
    if policy == "end":
        return segment[1]
    raise ValueError("Unknown forced exit policy: {}".format(policy))


def resolve_route(route, segments, forced_exits=None):
    forced_exits = forced_exits or {}
    rows = []
    for name in route:
        if name not in segments:
            raise ValueError("Unknown duct segment: {}".format(name))
        rows.append({"name": name, "segment": segments[name], "entry": None, "exit": None})

    if not rows:
        raise ValueError("Route must contain at least one duct segment")

    rows[0]["entry"] = rows[0]["segment"][0]

    links = []
    for index in range(len(rows) - 1):
        current = rows[index]
        following = rows[index + 1]
        start, end = current["segment"]
        next_start, next_end = following["segment"]
        policy = forced_exits.get((current["name"], following["name"]))
        if policy is not None:
            exit_point = forced_exit_point(current["segment"], policy)
            entry_point = closest_point_on_segment(following["segment"], exit_point)
            forced = True
        else:
            exit_point, entry_point = closest_points_segments(start, end, next_start, next_end)
            forced = False
        current["exit"] = exit_point
        following["entry"] = entry_point
        links.append(
            {
                "from": current["name"],
                "to": following["name"],
                "exit": exit_point,
                "entry": entry_point,
                "length": (entry_point - exit_point).Length,
                "forced": forced,
                "policy": policy,
            }
        )

    rows[-1]["exit"] = rows[-1]["segment"][1]

    pieces = []
    for index, row in enumerate(rows):
        entry = row["entry"]
        exit_point = row["exit"]
        length = (exit_point - entry).Length
        if length > EPS:
            pieces.append(
                {
                    "kind": "duct",
                    "row": index,
                    "name": row["name"],
                    "start": entry,
                    "end": exit_point,
                    "length": length,
                }
            )

        if index < len(links):
            link = links[index]
            if link["length"] > EPS:
                pieces.append(
                    {
                        "kind": "bridge",
                        "row": index,
                        "name": "{}->{}".format(link["from"], link["to"]),
                        "start": link["exit"],
                        "end": link["entry"],
                        "length": link["length"],
                    }
                )

    return rows, links, pieces


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


def biarc_edges(start, start_tangent, end, end_tangent, root_sign=1.0):
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
        2.0 * dot_product + root_sign * math.sqrt(discriminant)
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


def solve_transition_for_aim(
    start_point,
    start_tangent,
    target_start,
    target_end,
    radius,
    aim_point,
):
    first = solve_first_arc(start_point, start_tangent, aim_point, radius)
    target_direction = unit_vector(target_end - target_start)
    direction = first["direction"]
    cosine = clamp(direction.dot(target_direction), -1.0, 1.0)
    turn = math.acos(cosine)
    if turn < 1e-6:
        raise ValueError("Transition line already follows the target")
    if turn > math.pi - 1e-6:
        raise ValueError("Transition line is anti-parallel to the target")

    offset = radius * math.tan(turn / 2.0)
    p2 = aim_point - direction * offset
    q = aim_point + target_direction * offset
    line_length = (p2 - first["p1"]).dot(direction)
    if line_length <= 1e-9:
        raise ValueError("Fillet would start before the first arc")

    entry_param = raw_segment_param((target_start, target_end), q)
    if entry_param < -1e-9 or entry_param > 1.0 + 1e-9:
        raise ValueError("Entry point lies outside the target segment")

    side = unit_vector(target_direction - direction * cosine)
    center2 = p2 + side * radius
    arc2, angle2, normal2 = arc_from_start_tangent(center2, p2, q, direction)
    line = Part.makeLine(first["p1"], p2)

    transition_length = first["arc"].Length + line.Length + arc2.Length
    pieces = [
        {
            "kind": "arc",
            "name": "transition arc 1",
            "edge": first["arc"],
            "length": first["arc"].Length,
            "start": start_point,
            "end": first["p1"],
        },
        {
            "kind": "line",
            "name": "transition line",
            "edge": line,
            "length": line.Length,
            "start": first["p1"],
            "end": p2,
        },
        {
            "kind": "arc",
            "name": "transition arc 2",
            "edge": arc2,
            "length": arc2.Length,
            "start": p2,
            "end": q,
        },
    ]

    return {
        "strategy": "arc_line_arc",
        "radius": radius,
        "start_point": start_point,
        "start_tangent": unit_vector(start_tangent),
        "target_start": target_start,
        "target_end": target_end,
        "target_direction": target_direction,
        "aim_point": aim_point,
        "aim_param": raw_segment_param((target_start, target_end), aim_point),
        "first": first,
        "direction": direction,
        "turn": turn,
        "offset": offset,
        "p2": p2,
        "q": q,
        "line": line,
        "line_length": line_length,
        "center2": center2,
        "normal2": normal2,
        "arc2": arc2,
        "angle2": angle2,
        "entry_param": entry_param,
        "transition_length": transition_length,
        "pieces": pieces,
        "arc_centers": [first["center"], center2],
    }


def solve_arc_transition(
    start_point,
    start_tangent,
    target_start,
    target_end,
    radius,
    entry_param,
):
    samples = 41
    sampled = []
    for index in range(samples):
        aim_param = index / float(samples - 1)
        aim_point = target_start + (target_end - target_start) * aim_param
        try:
            result = solve_transition_for_aim(
                start_point,
                start_tangent,
                target_start,
                target_end,
                radius,
                aim_point,
            )
        except ValueError:
            sampled.append((aim_param, None))
        else:
            sampled.append((aim_param, result["entry_param"]))

    bracket = None
    increasing = True
    for index in range(samples - 1):
        a_param, a_entry = sampled[index]
        b_param, b_entry = sampled[index + 1]
        if a_entry is None or b_entry is None:
            continue
        if (a_entry - entry_param) * (b_entry - entry_param) <= 0.0:
            bracket = (a_param, b_param)
            increasing = b_entry >= a_entry
            break

    if bracket is None:
        raise ValueError("Requested target entry parameter is not reachable")

    low, high = bracket
    for _ in range(80):
        middle = (low + high) / 2.0
        aim_point = target_start + (target_end - target_start) * middle
        try:
            middle_result = solve_transition_for_aim(
                start_point,
                start_tangent,
                target_start,
                target_end,
                radius,
                aim_point,
            )
        except ValueError:
            high = middle
            continue
        if increasing:
            if middle_result["entry_param"] < entry_param:
                low = middle
            else:
                high = middle
        else:
            if middle_result["entry_param"] > entry_param:
                low = middle
            else:
                high = middle

    aim_param = (low + high) / 2.0
    aim_point = target_start + (target_end - target_start) * aim_param
    result = solve_transition_for_aim(
        start_point,
        start_tangent,
        target_start,
        target_end,
        radius,
        aim_point,
    )
    result["aim_param"] = aim_param
    if abs(result["entry_param"] - entry_param) > 1e-6:
        raise ValueError("Could not converge on the requested entry parameter")
    return result


def solve_biarc_line_arc(
    start_point,
    start_tangent,
    target_start,
    target_end,
    radius,
    entry_param,
    straight_length,
    line_direction=None,
):
    target_segment = (target_start, target_end)
    target_direction = unit_vector(target_end - target_start)
    target_length = (target_end - target_start).Length

    if line_direction is None:
        closest = closest_point_on_segment(target_segment, start_point)
        line_direction = unit_vector(closest - start_point)

    direction = unit_vector(line_direction)
    cosine = clamp(direction.dot(target_direction), -1.0, 1.0)
    turn = math.acos(cosine)
    if turn < 1e-6:
        raise ValueError("Direct line already follows the target")
    if turn > math.pi - 1e-6:
        raise ValueError("Direct line is anti-parallel to the target")

    offset = radius * math.tan(turn / 2.0)
    line_param = entry_param - offset / target_length
    if line_param < 0.0 or line_param > 1.0:
        raise ValueError("Placed line intersection lies outside the target segment")

    line_point = target_start + (target_end - target_start) * line_param
    p2 = line_point - direction * offset
    q = line_point + target_direction * offset

    fillet_side = unit_vector(target_direction - direction * cosine)
    fillet_center = p2 + fillet_side * radius
    fillet_arc, fillet_angle, _ = arc_from_start_tangent(
        fillet_center,
        p2,
        q,
        direction,
    )

    p1 = p2 - direction * straight_length
    arcs, joint, joint_tangent = biarc_edges(
        start_point,
        start_tangent,
        p1,
        direction,
    )
    if len(arcs) != 2:
        raise ValueError("Bi-arc is degenerate")

    line = Part.makeLine(p1, p2)
    pieces = [
        {
            "kind": "arc",
            "name": "bi-arc 1",
            "edge": arcs[0],
            "length": arcs[0].Length,
            "start": start_point,
            "end": joint,
        },
        {
            "kind": "arc",
            "name": "bi-arc 2",
            "edge": arcs[1],
            "length": arcs[1].Length,
            "start": joint,
            "end": p1,
        },
        {
            "kind": "line",
            "name": "shifted direct line",
            "edge": line,
            "length": line.Length,
            "start": p1,
            "end": p2,
        },
        {
            "kind": "arc",
            "name": "entry fillet",
            "edge": fillet_arc,
            "length": fillet_arc.Length,
            "start": p2,
            "end": q,
        },
    ]

    biarc_radii = []
    arc_centers = []
    for arc in arcs:
        curve = arc.Curve
        if isinstance(curve, Part.Circle):
            biarc_radii.append(curve.Radius)
            arc_centers.append(curve.Center)
        else:
            biarc_radii.append(None)
    arc_centers.append(fillet_center)

    transition_length = sum(piece["length"] for piece in pieces)
    return {
        "strategy": "biarc_line_arc",
        "radius": radius,
        "start_point": start_point,
        "start_tangent": unit_vector(start_tangent),
        "target_start": target_start,
        "target_end": target_end,
        "target_direction": target_direction,
        "line_direction": direction,
        "line_param": line_param,
        "line_point": line_point,
        "p1": p1,
        "p2": p2,
        "q": q,
        "joint": joint,
        "joint_tangent": joint_tangent,
        "straight_length": straight_length,
        "biarc_radii": biarc_radii,
        "fillet_radius": radius,
        "fillet_angle": fillet_angle,
        "fillet_center": fillet_center,
        "fillet_arc": fillet_arc,
        "entry_param": raw_segment_param(target_segment, q),
        "transition_length": transition_length,
        "pieces": pieces,
        "arc_centers": arc_centers,
    }


def solve_s5_fixed_arc_biarc_arc(
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
        raise ValueError("Fixed-arc biarc entry lies outside the target segment")

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
        raise ValueError("Last fixed arc does not meet the target tangentially")

    arcs, joint, joint_tangent = biarc_edges(p1, direction, p2, normal)
    if len(arcs) != 2:
        raise ValueError("Single bi-arc interconnect is degenerate")
    if arcs[-1].tangentAt(arcs[-1].LastParameter).dot(normal) < 1.0 - 1e-6:
        raise ValueError("Single bi-arc does not meet the last fixed arc tangentially")

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
    min_radius = min(radii) if radii else None
    return {
        "mode": "fixed_arcs",
        "pieces": pieces,
        "q": q,
        "entry_param": entry_param,
        "transition_length": sum(piece["length"] for piece in pieces),
        "min_radius": min_radius,
        "biarc_radii": [
            arc.Curve.Radius
            for arc in arcs
            if isinstance(arc.Curve, Part.Circle)
        ],
        "normal": normal,
        "p2": p2,
        "joint": joint,
        "root_sign": 1.0,
        "start_point": start_point,
        "aim": aim,
        "last_aim": last_aim,
        "first": first,
        "radius": radius,
    }


solve_s5 = solve_s5_fixed_arc_biarc_arc


def solve_align_arc_line_arc(
    start_point,
    start_tangent,
    target_start,
    target_end,
    radius,
    entry_param,
):
    tangent = unit_vector(start_tangent)
    target_direction = unit_vector(target_end - target_start)
    cosine = clamp(tangent.dot(target_direction), -1.0, 1.0)
    turn = math.acos(cosine)

    if turn < 1e-6:
        second = solve_arc_transition(
            start_point,
            tangent,
            target_start,
            target_end,
            radius,
            entry_param,
        )
        return {
            "strategy": "align_arc_line_arc",
            "radius": radius,
            "start_point": start_point,
            "start_tangent": tangent,
            "target_start": target_start,
            "target_end": target_end,
            "target_direction": target_direction,
            "orientation_arc": None,
            "orientation_center": None,
            "orientation_angle": 0.0,
            "orientation_end": start_point,
            "orientation_tangent": tangent,
            "second": second,
            "q": second["q"],
            "entry_param": second["entry_param"],
            "transition_length": second["transition_length"],
            "pieces": list(second["pieces"]),
            "arc_centers": list(second.get("arc_centers", [])),
        }

    if turn > math.pi - 1e-6:
        raise ValueError("Start tangent is anti-parallel to the target")

    side = unit_vector(target_direction - tangent * cosine)
    center = start_point + side * radius
    end_point = (
        start_point
        + tangent * (radius * math.sin(turn))
        + side * (radius * (1.0 - math.cos(turn)))
    )
    orientation_arc, orientation_angle, _ = arc_from_start_tangent(
        center,
        start_point,
        end_point,
        tangent,
    )

    second = solve_arc_transition(
        end_point,
        target_direction,
        target_start,
        target_end,
        radius,
        entry_param,
    )

    orientation_piece = {
        "kind": "arc",
        "name": "orientation arc",
        "edge": orientation_arc,
        "length": orientation_arc.Length,
        "start": start_point,
        "end": end_point,
    }
    pieces = [orientation_piece] + list(second["pieces"])

    return {
        "strategy": "align_arc_line_arc",
        "radius": radius,
        "start_point": start_point,
        "start_tangent": tangent,
        "target_start": target_start,
        "target_end": target_end,
        "target_direction": target_direction,
        "orientation_arc": orientation_arc,
        "orientation_center": center,
        "orientation_angle": orientation_angle,
        "orientation_end": end_point,
        "orientation_tangent": target_direction,
        "second": second,
        "q": second["q"],
        "entry_param": second["entry_param"],
        "transition_length": orientation_arc.Length + second["transition_length"],
        "pieces": pieces,
        "arc_centers": [center] + list(second.get("arc_centers", [])),
    }


def solve_perpendicular_line_arc(
    start_point,
    start_tangent,
    target_start,
    target_end,
    radius,
):
    tangent = unit_vector(start_tangent)
    target_direction = unit_vector(target_end - target_start)
    target_length = (target_end - target_start).Length
    cosine = clamp(tangent.dot(target_direction), -1.0, 1.0)
    turn = math.acos(cosine)

    if turn < 1e-6:
        raise ValueError("Start tangent is already parallel to the target")
    if turn > math.pi - 1e-6:
        raise ValueError("Start tangent is anti-parallel to the target")

    side = unit_vector(target_direction - tangent * cosine)
    orientation_center = start_point + side * radius
    orientation_end = (
        start_point
        + tangent * (radius * math.sin(turn))
        + side * (radius * (1.0 - math.cos(turn)))
    )
    orientation_arc, orientation_angle, _ = arc_from_start_tangent(
        orientation_center,
        start_point,
        orientation_end,
        tangent,
    )

    foot_param = (orientation_end - target_start).dot(target_direction)
    foot_point = target_start + target_direction * foot_param
    to_target = foot_point - orientation_end
    distance = to_target.Length
    if distance < 1e-9:
        raise ValueError("Alignment end lies on the target line")
    perpendicular_direction = unit_vector(to_target)
    if distance <= 2.0 * radius + 1e-9:
        raise ValueError("Perpendicular line would have non-positive length")

    arc_a_center = orientation_end + perpendicular_direction * radius
    arc_a_end = (
        orientation_end
        + target_direction * radius
        + perpendicular_direction * radius
    )
    arc_a, arc_a_angle, _ = arc_from_start_tangent(
        arc_a_center,
        orientation_end,
        arc_a_end,
        target_direction,
    )

    line_end = (
        foot_point
        + target_direction * radius
        - perpendicular_direction * radius
    )
    line = Part.makeLine(arc_a_end, line_end)
    line_length = (line_end - arc_a_end).dot(perpendicular_direction)
    if line_length <= 1e-9:
        raise ValueError("Perpendicular line is degenerate")

    q = foot_point + target_direction * (2.0 * radius)
    entry_param = raw_segment_param((target_start, target_end), q)
    if entry_param < -1e-9 or entry_param > 1.0 + 1e-9:
        raise ValueError("Perpendicular transition entry lies outside the target segment")

    fillet_center = q - perpendicular_direction * radius
    fillet_arc, fillet_angle, _ = arc_from_start_tangent(
        fillet_center,
        line_end,
        q,
        perpendicular_direction,
    )

    pieces = [
        {
            "kind": "arc",
            "name": "orientation arc",
            "edge": orientation_arc,
            "length": orientation_arc.Length,
            "start": start_point,
            "end": orientation_end,
        },
        {
            "kind": "arc",
            "name": "perpendicular turn arc",
            "edge": arc_a,
            "length": arc_a.Length,
            "start": orientation_end,
            "end": arc_a_end,
        },
        {
            "kind": "line",
            "name": "perpendicular line",
            "edge": line,
            "length": line.Length,
            "start": arc_a_end,
            "end": line_end,
        },
        {
            "kind": "arc",
            "name": "entry fillet",
            "edge": fillet_arc,
            "length": fillet_arc.Length,
            "start": line_end,
            "end": q,
        },
    ]

    return {
        "strategy": "perpendicular_line_arc",
        "radius": radius,
        "start_point": start_point,
        "start_tangent": tangent,
        "target_start": target_start,
        "target_end": target_end,
        "target_direction": target_direction,
        "orientation_arc": orientation_arc,
        "orientation_center": orientation_center,
        "orientation_angle": orientation_angle,
        "orientation_end": orientation_end,
        "orientation_tangent": target_direction,
        "perpendicular_direction": perpendicular_direction,
        "foot_point": foot_point,
        "foot_param": foot_param / target_length,
        "line": line,
        "line_length": line_length,
        "line_intersection_param": (foot_param + radius) / target_length,
        "arc_a": arc_a,
        "arc_a_angle": arc_a_angle,
        "arc_a_center": arc_a_center,
        "fillet_arc": fillet_arc,
        "fillet_angle": fillet_angle,
        "fillet_center": fillet_center,
        "q": q,
        "entry_param": entry_param,
        "transition_length": sum(piece["length"] for piece in pieces),
        "pieces": pieces,
        "arc_centers": [orientation_center, arc_a_center, fillet_center],
    }


def build_smooth_pieces(rows, links, transition):
    pieces = []
    pending_entry = rows[0]["entry"]

    for index, row in enumerate(rows):
        entry = pending_entry
        exit_point = row["exit"]
        run_length = (exit_point - entry).Length
        if run_length > EPS:
            pieces.append(
                {
                    "kind": "duct",
                    "name": row["name"],
                    "edge": Part.makeLine(entry, exit_point),
                    "length": run_length,
                    "start": entry,
                    "end": exit_point,
                }
            )

        if index < len(links):
            link = links[index]
            if link.get("forced") and transition is not None:
                pieces.extend(transition["pieces"])
                pending_entry = transition["q"]
            else:
                bridge_start = exit_point
                bridge_end = rows[index + 1]["entry"]
                bridge_length = (bridge_end - bridge_start).Length
                if bridge_length > EPS:
                    pieces.append(
                        {
                            "kind": "bridge",
                            "name": "{}->{}".format(link["from"], link["to"]),
                            "edge": Part.makeLine(bridge_start, bridge_end),
                            "length": bridge_length,
                            "start": bridge_start,
                            "end": bridge_end,
                        }
                    )
                pending_entry = bridge_end

    return pieces


def build_wire(pieces):
    edges = []
    for piece in pieces:
        edge = piece.get("edge")
        if edge is None:
            edge = Part.makeLine(piece["start"], piece["end"])
        edges.append(edge)
    if not edges:
        return None
    return Part.Wire(edges)


def build_cable(wire, diameter=CABLE_DIAMETER):
    if wire is None or not wire.Edges:
        return None
    first = wire.Edges[0]
    start = first.valueAt(first.FirstParameter)
    tangent = first.tangentAt(first.FirstParameter)
    profile = Part.Wire([Part.Circle(start, tangent, diameter / 2.0).toShape()])
    return wire.makePipeShell([profile], True, True, 2)


def view_property(obj, **properties):
    if not getattr(App, "GuiUp", False):
        return
    view = getattr(obj, "ViewObject", None)
    if view is None:
        return
    for key, value in properties.items():
        try:
            setattr(view, key, value)
        except Exception:
            pass


def add_feature(document, group, name, label, shape):
    obj = document.addObject("Part::Feature", name)
    obj.Label = label
    obj.Shape = shape
    if group is not None:
        group.addObject(obj)
    return obj


def prepare_document():
    document = App.listDocuments().get(DOC_NAME)
    if document is None:
        document = App.newDocument(DOC_NAME)
    else:
        for obj in reversed(list(document.Objects)):
            try:
                document.removeObject(obj.Name)
            except Exception:
                pass
        document.recompute()

    App.setActiveDocument(document.Name)
    return document


def print_route(route, segments, forced_exits=None, title="Route"):
    rows, links, pieces = resolve_route(route, segments, forced_exits)
    total = sum(piece["length"] for piece in pieces)

    print("{}: {}   total={:.4f} mm".format(title, " -> ".join(route), total))
    for index, row in enumerate(rows):
        entry_t = segment_param(row["segment"], row["entry"])
        exit_t = segment_param(row["segment"], row["exit"])
        run_length = (row["exit"] - row["entry"]).Length
        print(
            "  {}. {:<8s} t_in={:.3f} ({:<14s}) t_out={:.3f} ({:<14s}) run={:.4f}".format(
                index + 1,
                row["name"],
                entry_t,
                param_kind(entry_t),
                exit_t,
                param_kind(exit_t),
                run_length,
            )
        )
        if index < len(links):
            link = links[index]
            forced = " [forced {}]".format(link["policy"]) if link.get("forced") else ""
            print(
                "     bridge {:<8s} -> {:<8s} {:.4f} mm{}".format(
                    link["from"],
                    link["to"],
                    link["length"],
                    forced,
                )
            )
            print(
                "       exit  ({:8.3f}, {:8.3f}, {:8.3f})  [{}]".format(
                    link["exit"].x,
                    link["exit"].y,
                    link["exit"].z,
                    param_kind(segment_param(row["segment"], link["exit"])),
                )
            )
            next_row = rows[index + 1]
            print(
                "       entry ({:8.3f}, {:8.3f}, {:8.3f})  [{}]".format(
                    link["entry"].x,
                    link["entry"].y,
                    link["entry"].z,
                    param_kind(segment_param(next_row["segment"], link["entry"])),
                )
            )

    return rows, links, pieces, total


def print_transition(transition, smooth_total, straight_total):
    first = transition["first"]
    print(
        "Arc transition: R={:.1f} mm ({:.1f} x wire diameter), target entry t={:.3f}".format(
            transition["radius"],
            ARC_RADIUS_FACTOR,
            ARC_ENTRY_PARAM,
        )
    )
    print(
        "  aim point t={:.4f} ({:8.3f}, {:8.3f}, {:8.3f})".format(
            transition["aim_param"],
            transition["aim_point"].x,
            transition["aim_point"].y,
            transition["aim_point"].z,
        )
    )
    print(
        "  arc 1: angle={:7.2f} deg  length={:8.4f}  radius={:.3f}".format(
            math.degrees(first["angle"]),
            first["arc"].Length,
            first["arc"].Curve.Radius,
        )
    )
    print(
        "  line:  length={:8.4f}  direction=({:.3f}, {:.3f}, {:.3f})".format(
            transition["line_length"],
            transition["direction"].x,
            transition["direction"].y,
            transition["direction"].z,
        )
    )
    print(
        "  arc 2: angle={:7.2f} deg  length={:8.4f}  radius={:.3f}".format(
            math.degrees(transition["angle2"]),
            transition["arc2"].Length,
            transition["arc2"].Curve.Radius,
        )
    )
    print(
        "  entry: t={:.4f} ({:8.3f}, {:8.3f}, {:8.3f})".format(
            transition["entry_param"],
            transition["q"].x,
            transition["q"].y,
            transition["q"].z,
        )
    )
    print("  transition length: {:.4f} mm".format(transition["transition_length"]))
    print(
        "  smooth route total: {:.4f} mm (straight forced route: {:.4f} mm)".format(
            smooth_total,
            straight_total,
        )
    )


def print_biarc_transition(transition, smooth_total, straight_total):
    print(
        "Bi-arc -> shifted line -> simple arc: R={:.1f} mm, entry t={:.3f}, straight={:.1f} mm".format(
            transition["radius"],
            transition["entry_param"],
            transition["straight_length"],
        )
    )
    print(
        "  direct line direction: ({:.3f}, {:.3f}, {:.3f})".format(
            transition["line_direction"].x,
            transition["line_direction"].y,
            transition["line_direction"].z,
        )
    )
    print(
        "  line intersection: t={:.4f} ({:8.3f}, {:8.3f}, {:8.3f})".format(
            transition["line_param"],
            transition["line_point"].x,
            transition["line_point"].y,
            transition["line_point"].z,
        )
    )
    for index, piece in enumerate(transition["pieces"], start=1):
        if piece["kind"] == "arc":
            radius = piece["edge"].Curve.Radius
            print(
                "  {}. {:<20s} radius={:8.3f} angle={:7.2f} deg length={:8.4f}".format(
                    index,
                    piece["name"],
                    radius,
                    math.degrees(piece["length"] / radius),
                    piece["length"],
                )
            )
        else:
            print(
                "  {}. {:<20s} length={:8.4f}".format(
                    index,
                    piece["name"],
                    piece["length"],
                )
            )
    print(
        "  bi-arc joint: ({:8.3f}, {:8.3f}, {:8.3f})".format(
            transition["joint"].x,
            transition["joint"].y,
            transition["joint"].z,
        )
    )
    print(
        "  entry: t={:.4f} ({:8.3f}, {:8.3f}, {:8.3f})".format(
            transition["entry_param"],
            transition["q"].x,
            transition["q"].y,
            transition["q"].z,
        )
    )
    print("  transition length: {:.4f} mm".format(transition["transition_length"]))
    print(
        "  smooth route total: {:.4f} mm (straight forced route: {:.4f} mm)".format(
            smooth_total,
            straight_total,
        )
    )


def print_align_arc_line_arc(transition, smooth_total, straight_total):
    second = transition["second"]
    print(
        "Alignment arc -> arc -> line -> arc: R={:.1f} mm, entry t={:.3f}".format(
            transition["radius"],
            transition["entry_param"],
        )
    )
    if transition["orientation_arc"] is not None:
        print(
            "  orientation arc: angle={:7.2f} deg  length={:8.4f}  radius={:.3f}".format(
                math.degrees(transition["orientation_angle"]),
                transition["orientation_arc"].Length,
                transition["orientation_arc"].Curve.Radius,
            )
        )
        print(
            "  orientation end: ({:8.3f}, {:8.3f}, {:8.3f})  tangent parallel to target".format(
                transition["orientation_end"].x,
                transition["orientation_end"].y,
                transition["orientation_end"].z,
            )
        )
    print("  second stage:")
    print(
        "    aim point t={:.4f} ({:8.3f}, {:8.3f}, {:8.3f})".format(
            second["aim_param"],
            second["aim_point"].x,
            second["aim_point"].y,
            second["aim_point"].z,
        )
    )
    print(
        "    arc 1: angle={:7.2f} deg  length={:8.4f}  radius={:.3f}".format(
            math.degrees(second["first"]["angle"]),
            second["first"]["arc"].Length,
            second["first"]["arc"].Curve.Radius,
        )
    )
    print(
        "    line:  length={:8.4f}  direction=({:.3f}, {:.3f}, {:.3f})".format(
            second["line_length"],
            second["direction"].x,
            second["direction"].y,
            second["direction"].z,
        )
    )
    print(
        "    arc 2: angle={:7.2f} deg  length={:8.4f}  radius={:.3f}".format(
            math.degrees(second["angle2"]),
            second["arc2"].Length,
            second["arc2"].Curve.Radius,
        )
    )
    print(
        "    entry: t={:.4f} ({:8.3f}, {:8.3f}, {:8.3f})".format(
            second["entry_param"],
            second["q"].x,
            second["q"].y,
            second["q"].z,
        )
    )
    print("  combined transition length: {:.4f} mm".format(transition["transition_length"]))
    print(
        "  smooth route total: {:.4f} mm (straight forced route: {:.4f} mm)".format(
            smooth_total,
            straight_total,
        )
    )


def print_perpendicular_line_arc(transition, smooth_total, straight_total):
    print(
        "Alignment arc -> 90-deg arc -> perpendicular line -> 90-deg arc: R={:.1f} mm, entry t={:.3f}".format(
            transition["radius"],
            transition["entry_param"],
        )
    )
    print(
        "  orientation arc: angle={:7.2f} deg  length={:8.4f}  radius={:.3f}".format(
            math.degrees(transition["orientation_angle"]),
            transition["orientation_arc"].Length,
            transition["orientation_arc"].Curve.Radius,
        )
    )
    print(
        "  perpendicular line: length={:8.4f}  direction=({:.3f}, {:.3f}, {:.3f})".format(
            transition["line_length"],
            transition["perpendicular_direction"].x,
            transition["perpendicular_direction"].y,
            transition["perpendicular_direction"].z,
        )
    )
    print(
        "  foot point t={:.4f}  line/target intersection t={:.4f}".format(
            transition["foot_param"],
            transition["line_intersection_param"],
        )
    )
    print(
        "  turn arc: angle={:7.2f} deg  length={:8.4f}  radius={:.3f}".format(
            math.degrees(transition["arc_a_angle"]),
            transition["arc_a"].Length,
            transition["arc_a"].Curve.Radius,
        )
    )
    print(
        "  entry fillet: angle={:7.2f} deg  length={:8.4f}  radius={:.3f}".format(
            math.degrees(transition["fillet_angle"]),
            transition["fillet_arc"].Length,
            transition["fillet_arc"].Curve.Radius,
        )
    )
    print(
        "  entry: t={:.4f} ({:8.3f}, {:8.3f}, {:8.3f})".format(
            transition["entry_param"],
            transition["q"].x,
            transition["q"].y,
            transition["q"].z,
        )
    )
    print("  combined transition length: {:.4f} mm".format(transition["transition_length"]))
    print(
        "  smooth route total: {:.4f} mm (straight forced route: {:.4f} mm)".format(
            smooth_total,
            straight_total,
        )
    )


def add_transition_objects(
    document,
    parent_group,
    prefix,
    label,
    transition,
    smooth_wire,
    smooth_cable,
    color,
):
    group = document.addObject("App::DocumentObjectGroup", prefix)
    group.Label = label
    parent_group.addObject(group)

    path = add_feature(
        document,
        group,
        "{}_Path".format(prefix),
        "{} Path".format(label),
        smooth_wire,
    )
    view_property(path, LineColor=color, LineWidth=4, ShapeColor=color)

    if smooth_cable is not None:
        cable_obj = add_feature(
            document,
            group,
            "{}_Cable".format(prefix),
            "{} Cable".format(label),
            smooth_cable,
        )
        view_property(cable_obj, ShapeColor=color, Transparency=85)

    marker_points = [transition["start_point"], transition["q"]]
    for piece in transition["pieces"]:
        marker_points.extend([piece["start"], piece["end"]])

    unique_points = []
    seen = set()
    for point in marker_points:
        key = (round(point.x, 6), round(point.y, 6), round(point.z, 6))
        if key in seen:
            continue
        seen.add(key)
        unique_points.append(point)

    markers = add_feature(
        document,
        group,
        "{}_Markers".format(prefix),
        "{} Markers".format(label),
        Part.makeCompound([Part.makeSphere(MARKER_RADIUS, point) for point in unique_points]),
    )
    view_property(markers, ShapeColor=(0.95, 0.15, 0.10), Transparency=0)

    centers = transition.get("arc_centers", [])
    if centers:
        center_obj = add_feature(
            document,
            group,
            "{}_Centers".format(prefix),
            "{} Arc Centers".format(label),
            Part.makeCompound([Part.makeSphere(1.2, point) for point in centers]),
        )
        view_property(center_obj, ShapeColor=(0.20, 0.40, 0.95), Transparency=0)

    return group


def build_document(
    straight_wire,
    arc_line_arc,
    arc_line_arc_wire,
    arc_line_arc_cable,
    biarc_line_arc,
    biarc_line_arc_wire,
    biarc_line_arc_cable,
    align_arc_line_arc,
    align_arc_line_arc_wire,
    align_arc_line_arc_cable,
    perpendicular_line_arc,
    perpendicular_line_arc_wire,
    perpendicular_line_arc_cable,
):
    document = prepare_document()
    group = document.addObject("App::DocumentObjectGroup", "M3_OpenDuctTest")
    group.Label = "M3 Open Duct Arc Transition Test"

    used = set(ROUTE)
    for name, (start, end) in SEGMENTS.items():
        axis = end - start
        if axis.Length <= EPS:
            continue
        duct = add_feature(
            document,
            group,
            "M3_Duct_{}".format(name),
            "Duct {} ({})".format(name, "unused" if name not in used else "route"),
            Part.makeCylinder(DUCT_RADIUS, axis.Length, start, axis.normalize()),
        )
        if name in used:
            view_property(duct, ShapeColor=(0.45, 0.47, 0.52), Transparency=85)
        else:
            view_property(duct, ShapeColor=(0.70, 0.70, 0.72), Transparency=90)

    if straight_wire is not None:
        straight = add_feature(
            document,
            group,
            "M3_StraightPath",
            "M3 Straight Forced Path",
            straight_wire,
        )
        view_property(
            straight,
            LineColor=(0.55, 0.55, 0.58),
            LineWidth=2,
            ShapeColor=(0.55, 0.55, 0.58),
        )

    if arc_line_arc is not None:
        add_transition_objects(
            document,
            group,
            "M3_ArcLineArc",
            "Arc -> line -> arc",
            arc_line_arc,
            arc_line_arc_wire,
            arc_line_arc_cable,
            (0.10, 0.85, 0.25),
        )

    if biarc_line_arc is not None:
        add_transition_objects(
            document,
            group,
            "M3_BiarcLineArc",
            "Bi-arc -> shifted line -> arc",
            biarc_line_arc,
            biarc_line_arc_wire,
            biarc_line_arc_cable,
            (0.15, 0.45, 0.95),
        )

    if align_arc_line_arc is not None:
        add_transition_objects(
            document,
            group,
            "M3_AlignArcLineArc",
            "Align arc -> arc -> line -> arc",
            align_arc_line_arc,
            align_arc_line_arc_wire,
            align_arc_line_arc_cable,
            (1.0, 0.55, 0.0),
        )

    if perpendicular_line_arc is not None:
        add_transition_objects(
            document,
            group,
            "M3_PerpLineArc",
            "Align arc -> 90 arc -> perpendicular line -> 90 arc",
            perpendicular_line_arc,
            perpendicular_line_arc_wire,
            perpendicular_line_arc_cable,
            (1.0, 0.30, 0.70),
        )

    document.recompute()
    return document


def run_straight_checks(rows, links, pieces, wire, cable):
    failures = []

    def check(name, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        suffix = " ({})".format(detail) if detail else ""
        print("  [{}] {}{}".format(status, name, suffix))
        if not condition:
            failures.append(name)

    total = sum(piece["length"] for piece in pieces)
    check("path total length", abs(total - EXPECTED_TOTAL) < 1e-6, "{:.6f} mm".format(total))

    angled_direction = SEGMENTS["angled"][1] - SEGMENTS["angled"][0]
    stem_to_angled = next(
        (link for link in links if link["from"] == "stem" and link["to"] == "angled"),
        None,
    )
    check("stem -> angled bridge exists", stem_to_angled is not None)
    if stem_to_angled is not None:
        check(
            "stem -> angled bridge is 20*sqrt(114)/3 mm",
            abs(stem_to_angled["length"] - EXPECTED_BRIDGE) < 1e-6,
            "{:.6f} mm".format(stem_to_angled["length"]),
        )
        check(
            "stem -> angled bridge starts at the stem end",
            (stem_to_angled["exit"] - SEGMENTS["stem"][1]).Length < 1e-6,
        )
        delta = stem_to_angled["entry"] - stem_to_angled["exit"]
        check(
            "stem -> angled bridge is perpendicular to the angled duct",
            abs(delta.dot(angled_direction)) < 1e-6,
            "dot={:.6f}".format(delta.dot(angled_direction)),
        )

    left_to_stem = next(
        (link for link in links if link["from"] == "left" and link["to"] == "stem"),
        None,
    )
    check(
        "left -> stem meets at the T junction",
        left_to_stem is not None and left_to_stem["length"] < 1e-6,
    )

    stem_row = next((row for row in rows if row["name"] == "stem"), None)
    angled_row = next((row for row in rows if row["name"] == "angled"), None)
    if stem_row is not None:
        exit_t = segment_param(stem_row["segment"], stem_row["exit"])
        check("stem exit is the stem end", abs(exit_t - 1.0) < 1e-6, "t={:.3f}".format(exit_t))
        check(
            "stem run reaches the stem end",
            abs((stem_row["exit"] - stem_row["entry"]).Length - 80.0) < 1e-6,
        )
    if angled_row is not None:
        entry_t = segment_param(angled_row["segment"], angled_row["entry"])
        check(
            "angled entry is at t=5/12",
            abs(entry_t - 5.0 / 12.0) < 1e-6,
            "t={:.6f}".format(entry_t),
        )

    check(
        "angled duct is 45 degrees in two planes",
        abs(abs(angled_direction.x) - abs(angled_direction.y)) < 1e-6
        and abs(abs(angled_direction.x) - abs(angled_direction.z)) < 1e-6
        and abs(angled_direction.z) > 1e-6,
        "dir=({:.3f}, {:.3f}, {:.3f})".format(
            angled_direction.x,
            angled_direction.y,
            angled_direction.z,
        ),
    )

    check("path has four straight pieces", len(pieces) == 4, "{}".format(len(pieces)))
    check("path starts at the left duct start", (pieces[0]["start"] - SEGMENTS["left"][0]).Length < 1e-6)
    check("path ends at the angled duct end", (pieces[-1]["end"] - SEGMENTS["angled"][1]).Length < 1e-6)
    check("wire is valid", wire is not None and wire.isValid())
    check("wire is connected", wire is not None and len(wire.Edges) == len(pieces))
    check(
        "cable sweep produces one solid",
        cable is not None and cable.isValid() and len(cable.Solids) == 1,
    )
    check("right T branch is not routed", "right" not in ROUTE)

    return failures


def run_arc_line_arc_checks(transition, smooth_pieces, smooth_wire, smooth_cable):
    failures = []

    def check(name, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        suffix = " ({})".format(detail) if detail else ""
        print("  [{}] {}{}".format(status, name, suffix))
        if not condition:
            failures.append(name)

    radius = transition["radius"]
    arc1 = transition["first"]["arc"]
    arc2 = transition["arc2"]
    start_point = transition["start_point"]
    start_tangent = transition["start_tangent"]
    direction = transition["direction"]
    target_direction = transition["target_direction"]
    p1 = transition["first"]["p1"]
    p2 = transition["p2"]
    q = transition["q"]
    center1 = transition["first"]["center"]
    center2 = transition["center2"]

    check("arc 1 radius", abs(arc1.Curve.Radius - radius) < 1e-6, "{:.6f} mm".format(arc1.Curve.Radius))
    check("arc 2 radius", abs(arc2.Curve.Radius - radius) < 1e-6, "{:.6f} mm".format(arc2.Curve.Radius))
    check(
        "arc 1 starts at the stem end",
        (arc1.valueAt(arc1.FirstParameter) - start_point).Length < 1e-6,
    )
    check(
        "arc 1 is tangent to the stem",
        arc1.tangentAt(arc1.FirstParameter).dot(start_tangent) > 1.0 - 1e-6,
    )
    check(
        "arc 1 end tangent matches the straight line",
        arc1.tangentAt(arc1.LastParameter).dot(direction) > 1.0 - 1e-6,
    )
    check(
        "arc 2 start tangent matches the straight line",
        arc2.tangentAt(arc2.FirstParameter).dot(direction) > 1.0 - 1e-6,
    )
    check(
        "arc 2 end tangent matches the target duct",
        arc2.tangentAt(arc2.LastParameter).dot(target_direction) > 1.0 - 1e-6,
    )
    check(
        "entry point matches the requested parameter",
        abs(transition["entry_param"] - ARC_ENTRY_PARAM) < 1e-6,
        "t={:.6f}".format(transition["entry_param"]),
    )
    check(
        "entry point lies on the target duct",
        0.0 <= transition["entry_param"] <= 1.0,
    )
    check("straight line length is positive", transition["line_length"] > 1e-6)
    check(
        "transition length matches its pieces",
        abs(
            transition["transition_length"]
            - sum(piece["length"] for piece in transition["pieces"])
        )
        < 1e-6,
    )

    projection_min = None
    for step in range(101):
        parameter = arc1.FirstParameter + (arc1.LastParameter - arc1.FirstParameter) * step / 100.0
        point = arc1.valueAt(parameter)
        projection = (point - start_point).dot(start_tangent)
        projection_min = projection if projection_min is None else min(projection_min, projection)
    check(
        "arc 1 stays outside the stem",
        projection_min is not None and projection_min >= -1e-6,
        "min projection={:.6f}".format(projection_min),
    )
    check(
        "arc 1 center is one radius from the stem line",
        abs((center1 - start_point).Length - radius) < 1e-6,
    )
    check(
        "arc 1 center foot is the stem end",
        abs((center1 - start_point).dot(start_tangent)) < 1e-6,
    )
    check(
        "arc 2 center is one radius from the entry point",
        abs((center2 - q).Length - radius) < 1e-6,
    )
    check(
        "arc 2 entry radius is perpendicular to the target",
        abs((center2 - q).dot(target_direction)) < 1e-6,
    )

    side_normal = unit_vector(center2 - q)
    side_min = None
    for step in range(101):
        parameter = arc2.FirstParameter + (arc2.LastParameter - arc2.FirstParameter) * step / 100.0
        point = arc2.valueAt(parameter)
        side = (point - q).dot(side_normal)
        side_min = side if side_min is None else min(side_min, side)
    check(
        "arc 2 stays outside the target line",
        side_min is not None and side_min >= -1e-6,
        "min side={:.6f}".format(side_min),
    )

    continuity_error = 0.0
    for index in range(len(smooth_pieces) - 1):
        continuity_error = max(
            continuity_error,
            (smooth_pieces[index]["end"] - smooth_pieces[index + 1]["start"]).Length,
        )
    check(
        "smooth path is continuous",
        continuity_error < 1e-6,
        "max gap={:.9f}".format(continuity_error),
    )
    check("smooth wire is valid", smooth_wire is not None and smooth_wire.isValid())
    check(
        "smooth wire has the expected edge count",
        smooth_wire is not None and len(smooth_wire.Edges) == len(smooth_pieces),
        "{} edges".format(len(smooth_wire.Edges) if smooth_wire is not None else 0),
    )
    check(
        "smooth cable sweep produces one solid",
        smooth_cable is not None and smooth_cable.isValid() and len(smooth_cable.Solids) == 1,
    )

    return failures


def run_biarc_line_arc_checks(transition, smooth_pieces, smooth_wire, smooth_cable):
    failures = []

    def check(name, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        suffix = " ({})".format(detail) if detail else ""
        print("  [{}] {}{}".format(status, name, suffix))
        if not condition:
            failures.append(name)

    pieces = transition["pieces"]
    biarc1 = pieces[0]["edge"]
    biarc2 = pieces[1]["edge"]
    line = pieces[2]["edge"]
    fillet = pieces[3]["edge"]
    radius = transition["radius"]
    start_point = transition["start_point"]
    start_tangent = transition["start_tangent"]
    target_direction = transition["target_direction"]
    q = transition["q"]

    check("bi-arc -> line -> arc has four pieces", len(pieces) == 4, "{}".format(len(pieces)))
    check(
        "bi-arc first arc starts at the stem end",
        (biarc1.valueAt(biarc1.FirstParameter) - start_point).Length < 1e-6,
    )
    check(
        "bi-arc first arc is tangent to the stem",
        biarc1.tangentAt(biarc1.FirstParameter).dot(start_tangent) > 1.0 - 1e-6,
    )
    check(
        "bi-arc joint tangent is continuous",
        biarc1.tangentAt(biarc1.LastParameter).dot(
            biarc2.tangentAt(biarc2.FirstParameter)
        )
        > 1.0 - 1e-6,
    )
    check(
        "bi-arc end tangent matches the shifted line",
        biarc2.tangentAt(biarc2.LastParameter).dot(transition["line_direction"])
        > 1.0 - 1e-6,
    )
    check(
        "shifted line direction is the original direct line",
        transition["line_direction"].dot(
            unit_vector(
                closest_point_on_segment(
                    (transition["target_start"], transition["target_end"]),
                    start_point,
                )
                - start_point
            )
        )
        > 1.0 - 1e-6,
    )
    check(
        "ordered line tangent matches the line",
        line.tangentAt(line.FirstParameter).dot(transition["line_direction"]) > 1.0 - 1e-6,
    )
    check(
        "entry fillet starts tangent to the line",
        fillet.tangentAt(fillet.FirstParameter).dot(transition["line_direction"])
        > 1.0 - 1e-6,
    )
    check(
        "entry fillet ends tangent to the target",
        fillet.tangentAt(fillet.LastParameter).dot(target_direction) > 1.0 - 1e-6,
    )
    check(
        "straight length matches the requested value",
        abs(transition["straight_length"] - BIARC_LINE_ARC_STRAIGHT_LENGTH) < 1e-6,
        "{:.6f} mm".format(transition["straight_length"]),
    )
    check(
        "entry point matches the requested parameter",
        abs(transition["entry_param"] - BIARC_LINE_ARC_ENTRY_PARAM) < 1e-6,
        "t={:.6f}".format(transition["entry_param"]),
    )
    check(
        "entry point lies on the target duct",
        0.0 <= transition["entry_param"] <= 1.0,
    )

    arc_radii = [biarc1.Curve.Radius, biarc2.Curve.Radius, fillet.Curve.Radius]
    check(
        "entry fillet radius",
        abs(fillet.Curve.Radius - radius) < 1e-6,
        "{:.6f} mm".format(fillet.Curve.Radius),
    )
    check(
        "all arc radii meet the radius parameter",
        min(arc_radii) >= radius - 1e-6,
        "min={:.6f} mm".format(min(arc_radii)),
    )
    check(
        "bi-arc radii reported",
        all(r is not None for r in transition["biarc_radii"]),
        "{:.3f} / {:.3f} mm".format(
            transition["biarc_radii"][0],
            transition["biarc_radii"][1],
        ),
    )

    projection_min = None
    for step in range(101):
        parameter = biarc1.FirstParameter + (biarc1.LastParameter - biarc1.FirstParameter) * step / 100.0
        point = biarc1.valueAt(parameter)
        projection = (point - start_point).dot(start_tangent)
        projection_min = projection if projection_min is None else min(projection_min, projection)
    check(
        "bi-arc first arc stays outside the stem",
        projection_min is not None and projection_min >= -1e-6,
        "min projection={:.6f}".format(projection_min),
    )

    side_normal = unit_vector(transition["fillet_center"] - q)
    side_min = None
    for step in range(101):
        parameter = fillet.FirstParameter + (fillet.LastParameter - fillet.FirstParameter) * step / 100.0
        point = fillet.valueAt(parameter)
        side = (point - q).dot(side_normal)
        side_min = side if side_min is None else min(side_min, side)
    check(
        "entry fillet stays outside the target line",
        side_min is not None and side_min >= -1e-6,
        "min side={:.6f}".format(side_min),
    )

    continuity_error = 0.0
    for index in range(len(smooth_pieces) - 1):
        continuity_error = max(
            continuity_error,
            (smooth_pieces[index]["end"] - smooth_pieces[index + 1]["start"]).Length,
        )
    check(
        "smooth path is continuous",
        continuity_error < 1e-6,
        "max gap={:.9f}".format(continuity_error),
    )
    check("smooth wire is valid", smooth_wire is not None and smooth_wire.isValid())
    check(
        "smooth wire has the expected edge count",
        smooth_wire is not None and len(smooth_wire.Edges) == len(smooth_pieces),
        "{} edges".format(len(smooth_wire.Edges) if smooth_wire is not None else 0),
    )
    check(
        "smooth cable sweep produces one solid",
        smooth_cable is not None and smooth_cable.isValid() and len(smooth_cable.Solids) == 1,
    )

    return failures


def run_align_arc_line_arc_checks(transition, smooth_pieces, smooth_wire, smooth_cable):
    failures = []

    def check(name, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        suffix = " ({})".format(detail) if detail else ""
        print("  [{}] {}{}".format(status, name, suffix))
        if not condition:
            failures.append(name)

    radius = transition["radius"]
    start_point = transition["start_point"]
    start_tangent = transition["start_tangent"]
    target_direction = transition["target_direction"]
    orientation_arc = transition["orientation_arc"]
    second = transition["second"]

    check("orientation arc exists", orientation_arc is not None)
    if orientation_arc is not None:
        check(
            "orientation arc radius",
            abs(orientation_arc.Curve.Radius - radius) < 1e-6,
            "{:.6f} mm".format(orientation_arc.Curve.Radius),
        )
        check(
            "orientation arc starts at the stem end",
            (orientation_arc.valueAt(orientation_arc.FirstParameter) - start_point).Length < 1e-6,
        )
        check(
            "orientation arc is tangent to the stem",
            orientation_arc.tangentAt(orientation_arc.FirstParameter).dot(start_tangent)
            > 1.0 - 1e-6,
        )
        check(
            "orientation arc ends parallel to the target",
            orientation_arc.tangentAt(orientation_arc.LastParameter).dot(target_direction)
            > 1.0 - 1e-6,
        )
        check(
            "orientation arc end is the second-stage start",
            (transition["orientation_end"] - second["start_point"]).Length < 1e-6,
        )

        projection_min = None
        for step in range(101):
            parameter = orientation_arc.FirstParameter + (
                orientation_arc.LastParameter - orientation_arc.FirstParameter
            ) * step / 100.0
            point = orientation_arc.valueAt(parameter)
            projection = (point - start_point).dot(start_tangent)
            projection_min = projection if projection_min is None else min(projection_min, projection)
        check(
            "orientation arc stays outside the stem",
            projection_min is not None and projection_min >= -1e-6,
            "min projection={:.6f}".format(projection_min),
        )

        separation_min = None
        second_arc1 = second["first"]["arc"]
        for step in range(1, 101):
            parameter = second_arc1.FirstParameter + (
                second_arc1.LastParameter - second_arc1.FirstParameter
            ) * step / 100.0
            point = second_arc1.valueAt(parameter)
            separation = orientation_arc.distToShape(Part.Vertex(point))[0]
            separation_min = separation if separation_min is None else min(separation_min, separation)
        check(
            "second-stage first arc clears the orientation arc",
            separation_min is not None and separation_min > 1e-3,
            "min distance={:.6f}".format(separation_min),
        )

    second_arc1 = second["first"]["arc"]
    second_arc2 = second["arc2"]
    check(
        "second-stage arc 1 radius",
        abs(second_arc1.Curve.Radius - radius) < 1e-6,
        "{:.6f} mm".format(second_arc1.Curve.Radius),
    )
    check(
        "second-stage arc 2 radius",
        abs(second_arc2.Curve.Radius - radius) < 1e-6,
        "{:.6f} mm".format(second_arc2.Curve.Radius),
    )
    check(
        "second-stage arc 1 starts at the orientation end",
        (second_arc1.valueAt(second_arc1.FirstParameter) - second["start_point"]).Length < 1e-6,
    )
    check(
        "second-stage arc 1 starts parallel to the target",
        second_arc1.tangentAt(second_arc1.FirstParameter).dot(target_direction) > 1.0 - 1e-6,
    )
    check(
        "second-stage arc 2 ends on the target tangent",
        second_arc2.tangentAt(second_arc2.LastParameter).dot(target_direction) > 1.0 - 1e-6,
    )
    check(
        "second-stage entry matches the requested parameter",
        abs(second["entry_param"] - ALIGN_ARC_ENTRY_PARAM) < 1e-6,
        "t={:.6f}".format(second["entry_param"]),
    )
    check(
        "second-stage entry lies on the target duct",
        0.0 <= second["entry_param"] <= 1.0,
    )

    q = second["q"]
    side_normal = unit_vector(second["center2"] - q)
    side_min = None
    for step in range(101):
        parameter = second_arc2.FirstParameter + (
            second_arc2.LastParameter - second_arc2.FirstParameter
        ) * step / 100.0
        point = second_arc2.valueAt(parameter)
        side = (point - q).dot(side_normal)
        side_min = side if side_min is None else min(side_min, side)
    check(
        "second-stage fillet stays outside the target line",
        side_min is not None and side_min >= -1e-6,
        "min side={:.6f}".format(side_min),
    )

    arc_radii = []
    if orientation_arc is not None:
        arc_radii.append(orientation_arc.Curve.Radius)
    arc_radii.extend([second_arc1.Curve.Radius, second_arc2.Curve.Radius])
    check(
        "all alignment arcs use the same radius",
        max(arc_radii) - min(arc_radii) < 1e-6 and abs(min(arc_radii) - radius) < 1e-6,
        "radii={}".format(", ".join("{:.3f}".format(value) for value in arc_radii)),
    )
    check(
        "combined transition length matches its pieces",
        abs(
            transition["transition_length"]
            - sum(piece["length"] for piece in transition["pieces"])
        )
        < 1e-6,
    )

    continuity_error = 0.0
    for index in range(len(smooth_pieces) - 1):
        continuity_error = max(
            continuity_error,
            (smooth_pieces[index]["end"] - smooth_pieces[index + 1]["start"]).Length,
        )
    check(
        "smooth path is continuous",
        continuity_error < 1e-6,
        "max gap={:.9f}".format(continuity_error),
    )
    check("smooth wire is valid", smooth_wire is not None and smooth_wire.isValid())
    check(
        "smooth wire has the expected edge count",
        smooth_wire is not None and len(smooth_wire.Edges) == len(smooth_pieces),
        "{} edges".format(len(smooth_wire.Edges) if smooth_wire is not None else 0),
    )
    check(
        "smooth cable sweep produces one solid",
        smooth_cable is not None and smooth_cable.isValid() and len(smooth_cable.Solids) == 1,
    )

    return failures


def run_perpendicular_line_arc_checks(transition, smooth_pieces, smooth_wire, smooth_cable):
    failures = []

    def check(name, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        suffix = " ({})".format(detail) if detail else ""
        print("  [{}] {}{}".format(status, name, suffix))
        if not condition:
            failures.append(name)

    radius = transition["radius"]
    start_point = transition["start_point"]
    start_tangent = transition["start_tangent"]
    target_direction = transition["target_direction"]
    orientation_arc = transition["orientation_arc"]
    arc_a = transition["arc_a"]
    line = transition["line"]
    fillet = transition["fillet_arc"]
    q = transition["q"]
    perpendicular = transition["perpendicular_direction"]

    check(
        "orientation arc radius",
        abs(orientation_arc.Curve.Radius - radius) < 1e-6,
        "{:.6f} mm".format(orientation_arc.Curve.Radius),
    )
    check(
        "orientation arc starts at the stem end",
        (orientation_arc.valueAt(orientation_arc.FirstParameter) - start_point).Length < 1e-6,
    )
    check(
        "orientation arc is tangent to the stem",
        orientation_arc.tangentAt(orientation_arc.FirstParameter).dot(start_tangent)
        > 1.0 - 1e-6,
    )
    check(
        "orientation arc ends parallel to the target",
        orientation_arc.tangentAt(orientation_arc.LastParameter).dot(target_direction)
        > 1.0 - 1e-6,
    )
    check(
        "orientation arc end is the turn arc start",
        (transition["orientation_end"] - arc_a.valueAt(arc_a.FirstParameter)).Length < 1e-6,
    )

    projection_min = None
    for step in range(101):
        parameter = orientation_arc.FirstParameter + (
            orientation_arc.LastParameter - orientation_arc.FirstParameter
        ) * step / 100.0
        point = orientation_arc.valueAt(parameter)
        projection = (point - start_point).dot(start_tangent)
        projection_min = projection if projection_min is None else min(projection_min, projection)
    check(
        "orientation arc stays outside the stem",
        projection_min is not None and projection_min >= -1e-6,
        "min projection={:.6f}".format(projection_min),
    )

    check(
        "perpendicular turn arc radius",
        abs(arc_a.Curve.Radius - radius) < 1e-6,
        "{:.6f} mm".format(arc_a.Curve.Radius),
    )
    check(
        "perpendicular turn arc starts parallel to the target",
        arc_a.tangentAt(arc_a.FirstParameter).dot(target_direction) > 1.0 - 1e-6,
    )
    check(
        "perpendicular turn arc ends along the perpendicular",
        arc_a.tangentAt(arc_a.LastParameter).dot(perpendicular) > 1.0 - 1e-6,
    )
    check(
        "perpendicular turn arc is 90 degrees",
        abs(transition["arc_a_angle"] - math.pi / 2.0) < 1e-6,
        "{:.6f} deg".format(math.degrees(transition["arc_a_angle"])),
    )

    check(
        "perpendicular line is perpendicular to the target",
        abs(perpendicular.dot(target_direction)) < 1e-6,
        "dot={:.9f}".format(perpendicular.dot(target_direction)),
    )
    check(
        "perpendicular line follows its direction",
        line.tangentAt(line.FirstParameter).dot(perpendicular) > 1.0 - 1e-6,
    )
    check(
        "perpendicular line starts at the turn arc end",
        (line.valueAt(line.FirstParameter) - arc_a.valueAt(arc_a.LastParameter)).Length < 1e-6,
    )
    check(
        "perpendicular line length matches the foot distance",
        abs(
            transition["line_length"]
            - ((transition["foot_point"] - transition["orientation_end"]).Length - 2.0 * radius)
        )
        < 1e-6,
        "{:.6f} mm".format(transition["line_length"]),
    )
    check(
        "perpendicular line stays one radius from the target",
        abs(line.distToShape(Part.makeLine(transition["target_start"], transition["target_end"]))[0] - radius)
        < 1e-6,
        "{:.6f} mm".format(
            line.distToShape(Part.makeLine(transition["target_start"], transition["target_end"]))[0]
        ),
    )

    check(
        "entry fillet radius",
        abs(fillet.Curve.Radius - radius) < 1e-6,
        "{:.6f} mm".format(fillet.Curve.Radius),
    )
    check(
        "entry fillet starts along the perpendicular",
        fillet.tangentAt(fillet.FirstParameter).dot(perpendicular) > 1.0 - 1e-6,
    )
    check(
        "entry fillet ends on the target tangent",
        fillet.tangentAt(fillet.LastParameter).dot(target_direction) > 1.0 - 1e-6,
    )
    check(
        "entry fillet is 90 degrees",
        abs(transition["fillet_angle"] - math.pi / 2.0) < 1e-6,
        "{:.6f} deg".format(math.degrees(transition["fillet_angle"])),
    )
    check(
        "perpendicular entry lies on the target duct",
        0.0 <= transition["entry_param"] <= 1.0,
        "t={:.6f}".format(transition["entry_param"]),
    )

    side_normal = unit_vector(transition["fillet_center"] - q)
    side_min = None
    for step in range(101):
        parameter = fillet.FirstParameter + (fillet.LastParameter - fillet.FirstParameter) * step / 100.0
        point = fillet.valueAt(parameter)
        side = (point - q).dot(side_normal)
        side_min = side if side_min is None else min(side_min, side)
    check(
        "entry fillet stays outside the target line",
        side_min is not None and side_min >= -1e-6,
        "min side={:.6f}".format(side_min),
    )

    arc_radii = [
        orientation_arc.Curve.Radius,
        arc_a.Curve.Radius,
        fillet.Curve.Radius,
    ]
    check(
        "all perpendicular-line arcs use the same radius",
        max(arc_radii) - min(arc_radii) < 1e-6 and abs(min(arc_radii) - radius) < 1e-6,
        "radii={}".format(", ".join("{:.3f}".format(value) for value in arc_radii)),
    )
    check(
        "combined transition length matches its pieces",
        abs(
            transition["transition_length"]
            - sum(piece["length"] for piece in transition["pieces"])
        )
        < 1e-6,
    )

    continuity_error = 0.0
    for index in range(len(smooth_pieces) - 1):
        continuity_error = max(
            continuity_error,
            (smooth_pieces[index]["end"] - smooth_pieces[index + 1]["start"]).Length,
        )
    check(
        "smooth path is continuous",
        continuity_error < 1e-6,
        "max gap={:.9f}".format(continuity_error),
    )
    check("smooth wire is valid", smooth_wire is not None and smooth_wire.isValid())
    check(
        "smooth wire has the expected edge count",
        smooth_wire is not None and len(smooth_wire.Edges) == len(smooth_pieces),
        "{} edges".format(len(smooth_wire.Edges) if smooth_wire is not None else 0),
    )
    check(
        "smooth cable sweep produces one solid",
        smooth_cable is not None and smooth_cable.isValid() and len(smooth_cable.Solids) == 1,
    )

    return failures


def main():
    print("VibeWire M3 open-duct transition comparison")
    print("=" * 49)

    rows, links, pieces, straight_total = print_route(
        ROUTE,
        SEGMENTS,
        FORCED_EXITS,
        title="Forced route",
    )
    print()
    print("Straight path pieces:")
    for index, piece in enumerate(pieces, start=1):
        print("  {}. {:<8s} {:<20s} {:8.4f} mm".format(index, piece["kind"], piece["name"], piece["length"]))
    print("  Total straight forced path: {:.4f} mm".format(straight_total))

    straight_wire = build_wire(pieces)
    straight_cable = build_cable(straight_wire)

    forced_index = next(index for index, link in enumerate(links) if link.get("forced"))
    forced_row = rows[forced_index]
    forced_link = links[forced_index]
    target_row = rows[forced_index + 1]
    start_point = forced_row["exit"]
    start_tangent = unit_vector(forced_row["exit"] - forced_row["entry"])
    target_start, target_end = target_row["segment"]
    direct_direction = unit_vector(forced_link["entry"] - forced_link["exit"])

    arc_line_arc = solve_arc_transition(
        start_point,
        start_tangent,
        target_start,
        target_end,
        ARC_RADIUS,
        ARC_ENTRY_PARAM,
    )
    arc_line_arc_pieces = build_smooth_pieces(rows, links, arc_line_arc)
    arc_line_arc_wire = build_wire(arc_line_arc_pieces)
    arc_line_arc_cable = build_cable(arc_line_arc_wire)
    arc_line_arc_total = sum(piece["length"] for piece in arc_line_arc_pieces)

    biarc_line_arc = solve_biarc_line_arc(
        start_point,
        start_tangent,
        target_start,
        target_end,
        ARC_RADIUS,
        BIARC_LINE_ARC_ENTRY_PARAM,
        BIARC_LINE_ARC_STRAIGHT_LENGTH,
        line_direction=direct_direction,
    )
    biarc_line_arc_pieces = build_smooth_pieces(rows, links, biarc_line_arc)
    biarc_line_arc_wire = build_wire(biarc_line_arc_pieces)
    biarc_line_arc_cable = build_cable(biarc_line_arc_wire)
    biarc_line_arc_total = sum(piece["length"] for piece in biarc_line_arc_pieces)

    align_arc_line_arc = solve_align_arc_line_arc(
        start_point,
        start_tangent,
        target_start,
        target_end,
        ARC_RADIUS,
        ALIGN_ARC_ENTRY_PARAM,
    )
    align_arc_line_arc_pieces = build_smooth_pieces(rows, links, align_arc_line_arc)
    align_arc_line_arc_wire = build_wire(align_arc_line_arc_pieces)
    align_arc_line_arc_cable = build_cable(align_arc_line_arc_wire)
    align_arc_line_arc_total = sum(piece["length"] for piece in align_arc_line_arc_pieces)

    perpendicular_line_arc = solve_perpendicular_line_arc(
        start_point,
        start_tangent,
        target_start,
        target_end,
        ARC_RADIUS,
    )
    perpendicular_line_arc_pieces = build_smooth_pieces(rows, links, perpendicular_line_arc)
    perpendicular_line_arc_wire = build_wire(perpendicular_line_arc_pieces)
    perpendicular_line_arc_cable = build_cable(perpendicular_line_arc_wire)
    perpendicular_line_arc_total = sum(
        piece["length"] for piece in perpendicular_line_arc_pieces
    )

    print()
    print("Solution 1: arc -> line -> arc (current)")
    print_transition(arc_line_arc, arc_line_arc_total, straight_total)

    print()
    print("Solution 2: bi-arc -> shifted line -> simple arc")
    print_biarc_transition(biarc_line_arc, biarc_line_arc_total, straight_total)

    print()
    print("Solution 3: alignment arc -> arc -> line -> arc")
    print_align_arc_line_arc(align_arc_line_arc, align_arc_line_arc_total, straight_total)

    print()
    print("Solution 4: alignment arc -> 90-deg arc -> perpendicular line -> 90-deg arc")
    print_perpendicular_line_arc(
        perpendicular_line_arc,
        perpendicular_line_arc_total,
        straight_total,
    )

    print()
    print("Complexity comparison:")
    print("  arc-line-arc   : custom first-arc trig solver + 41-sample aim scan + 80-step bisection")
    print("                   derived straight direction; both transition arcs exactly R")
    print("  biarc-line-arc : standard bi-arc solver + line placement/fillet algebra")
    print("                   original direct-line direction; free bi-arc radii + straight-length parameter")
    print("  align-arc-line : one fixed-radius alignment arc + the existing arc-line-arc solver")
    print("                   all arcs exactly R; no new solver, entry matches the current solution")
    print("  perpendicular  : alignment arc + 90-deg arc + perpendicular line + 90-deg fillet")
    print("                   all arcs exactly R; entry follows from the perpendicular foot")
    print(
        "  entry points: arc-line-arc={:.1f}  biarc-line-arc={:.1f}  align-arc-line={:.1f}  perpendicular={:.4f}".format(
            ARC_ENTRY_PARAM,
            BIARC_LINE_ARC_ENTRY_PARAM,
            ALIGN_ARC_ENTRY_PARAM,
            perpendicular_line_arc["entry_param"],
        )
    )
    print()
    print(
        "  arc-line-arc   transition={:8.4f}  full={:8.4f}  straight dir=({:.3f}, {:.3f}, {:.3f})".format(
            arc_line_arc["transition_length"],
            arc_line_arc_total,
            arc_line_arc["direction"].x,
            arc_line_arc["direction"].y,
            arc_line_arc["direction"].z,
        )
    )
    print(
        "  biarc-line-arc transition={:8.4f}  full={:8.4f}  straight dir=({:.3f}, {:.3f}, {:.3f})".format(
            biarc_line_arc["transition_length"],
            biarc_line_arc_total,
            biarc_line_arc["line_direction"].x,
            biarc_line_arc["line_direction"].y,
            biarc_line_arc["line_direction"].z,
        )
    )
    print(
        "  align-arc-line transition={:8.4f}  full={:8.4f}  straight dir=({:.3f}, {:.3f}, {:.3f})".format(
            align_arc_line_arc["transition_length"],
            align_arc_line_arc_total,
            align_arc_line_arc["second"]["direction"].x,
            align_arc_line_arc["second"]["direction"].y,
            align_arc_line_arc["second"]["direction"].z,
        )
    )
    print(
        "  perpendicular  transition={:8.4f}  full={:8.4f}  line dir=({:.3f}, {:.3f}, {:.3f})  perpendicular".format(
            perpendicular_line_arc["transition_length"],
            perpendicular_line_arc_total,
            perpendicular_line_arc["perpendicular_direction"].x,
            perpendicular_line_arc["perpendicular_direction"].y,
            perpendicular_line_arc["perpendicular_direction"].z,
        )
    )

    document = build_document(
        straight_wire,
        arc_line_arc,
        arc_line_arc_wire,
        arc_line_arc_cable,
        biarc_line_arc,
        biarc_line_arc_wire,
        biarc_line_arc_cable,
        align_arc_line_arc,
        align_arc_line_arc_wire,
        align_arc_line_arc_cable,
        perpendicular_line_arc,
        perpendicular_line_arc_wire,
        perpendicular_line_arc_cable,
    )

    print()
    print("Comparison:")
    print_route(ROUTE, SEGMENTS, None, title="Unforced route")

    print()
    print("Extra route orders (diagnostics only):")
    for route in EXTRA_ROUTES:
        print_route(route, SEGMENTS)

    print()
    print("Straight-route checks:")
    failures = run_straight_checks(rows, links, pieces, straight_wire, straight_cable)
    print()
    print("Solution 1 checks (arc -> line -> arc):")
    failures += run_arc_line_arc_checks(
        arc_line_arc,
        arc_line_arc_pieces,
        arc_line_arc_wire,
        arc_line_arc_cable,
    )
    print()
    print("Solution 2 checks (bi-arc -> shifted line -> arc):")
    failures += run_biarc_line_arc_checks(
        biarc_line_arc,
        biarc_line_arc_pieces,
        biarc_line_arc_wire,
        biarc_line_arc_cable,
    )
    print()
    print("Solution 3 checks (alignment arc -> arc -> line -> arc):")
    failures += run_align_arc_line_arc_checks(
        align_arc_line_arc,
        align_arc_line_arc_pieces,
        align_arc_line_arc_wire,
        align_arc_line_arc_cable,
    )
    print()
    print("Solution 4 checks (alignment arc -> 90 arc -> perpendicular line -> 90 arc):")
    failures += run_perpendicular_line_arc_checks(
        perpendicular_line_arc,
        perpendicular_line_arc_pieces,
        perpendicular_line_arc_wire,
        perpendicular_line_arc_cable,
    )
    print()
    if failures:
        print("RESULT: {} check(s) failed".format(len(failures)))
    else:
        print("RESULT: all checks passed")

    print("Objects in '{}': {}".format(document.Name, len(document.Objects)))

    if getattr(App, "GuiUp", False):
        try:
            import FreeCADGui as Gui

            Gui.activeDocument().activeView().fitAll()
        except Exception:
            pass

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
