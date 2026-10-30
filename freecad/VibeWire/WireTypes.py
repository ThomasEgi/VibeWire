"""Shared VibeWire object type helpers and constants."""

BUNDLE_SEGMENT_TYPE = "WireBundleSegment"
ROUTE_SEGMENT_ROLE = "Route"
LACE_HELPER_ROLE = "Lace Helper"


def is_bundle_segment(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == BUNDLE_SEGMENT_TYPE


def segment_is_open(segment):
    return getattr(segment, "SegmentType", "Closed") == "Open"


def is_lace_helper(obj):
    if getattr(obj, "SegmentRole", None) == LACE_HELPER_ROLE:
        return True
    return getattr(obj, "Label", "").startswith("Lace Helper ")


def is_harness(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) in (
        "WireHarness",
        "WireBundle",
    )


def is_wire_cable(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == "WireCable"
