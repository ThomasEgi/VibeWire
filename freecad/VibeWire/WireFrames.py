"""Bundle-segment coordinate frames."""

import math

import FreeCAD as App


def _reference_axis(ref, axis):
    if ref is None:
        return None
    try:
        return ref.getGlobalPlacement().Rotation.multVec(axis)
    except Exception:
        return None


def _averaged_reference_axis(start_ref, end_ref, axis):
    start_axis = _reference_axis(start_ref, axis)
    end_axis = _reference_axis(end_ref, axis)
    if start_axis is None and end_axis is None:
        return None
    if start_axis is None:
        return end_axis.normalize() if end_axis.Length > 1e-9 else None
    if end_axis is None:
        return start_axis.normalize() if start_axis.Length > 1e-9 else None
    combined = start_axis + end_axis
    if combined.Length < 1e-9:
        return start_axis.normalize()
    return combined.normalize()


def segment_side_vector(
    start, end, orientation=0.0, start_ref=None, end_ref=None
):
    """Lateral axis from the averaged reference frames plus manual roll."""
    direction = end - start
    length = direction.Length
    if length < 1e-9:
        return App.Vector(0.0, 0.0, 0.0)
    direction = direction / length

    side = None
    for axis in (
        App.Vector(0.0, 0.0, 1.0),
        App.Vector(0.0, 1.0, 0.0),
        App.Vector(1.0, 0.0, 0.0),
    ):
        up = _averaged_reference_axis(start_ref, end_ref, axis)
        if up is None:
            continue
        candidate = direction.cross(up)
        if candidate.Length > 1e-9:
            side = candidate.normalize()
            break

    if side is None:
        up = App.Vector(0.0, 0.0, 1.0)
        if abs(direction.dot(up)) > 0.99:
            up = App.Vector(0.0, 1.0, 0.0)
        side = direction.cross(up)
        if side.Length < 1e-9:
            side = direction.cross(App.Vector(1.0, 0.0, 0.0))
        side = side.normalize()

    if abs(orientation) > 1e-12:
        normal = direction.cross(side)
        if normal.Length > 1e-9:
            normal = normal.normalize()
            side = side * math.cos(orientation) + normal * math.sin(orientation)
    return side




def segment_basis(segment):
    start_obj = segment.Start
    end_obj = segment.End
    if start_obj is None or end_obj is None:
        return App.Vector(1.0, 0.0, 0.0), App.Vector(0.0, 1.0, 0.0)
    start = start_obj.getGlobalPlacement().Base
    end = end_obj.getGlobalPlacement().Base
    direction = end - start
    length = direction.Length
    if length < 1e-9:
        return App.Vector(1.0, 0.0, 0.0), App.Vector(0.0, 1.0, 0.0)
    direction = direction / length
    orientation = 0.0
    if "Orientation" in segment.PropertiesList:
        orientation = math.radians(segment.Orientation.Value)
    side = segment_side_vector(start, end, orientation, start_obj, end_obj)
    normal = direction.cross(side)
    if normal.Length < 1e-9:
        normal = App.Vector(0.0, 0.0, 1.0)
    else:
        normal = normal.normalize()
    return side, normal
