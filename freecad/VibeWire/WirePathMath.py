"""Shared arc and bi-arc primitives for VibeWire paths."""

import math

import Part

from .WireGeometry import unit_vector


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
