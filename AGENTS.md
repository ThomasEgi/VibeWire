# AGENTS.md - FreeCAD Wire/Cable Routing Plugin

## Commands, Shortcuts and Hints

### Python 
Use python's buildin dir() and help() methods when availability or usage of methods or classes are unclear or throw errors.

### FreeCAD-MCP
FreeCAD is set up with an MCP-bridge, use it when needed.
FreeCAD is running as appimage with its own python environment. 
All python code that needs to work with FreeCAD must be called using FreeCAD-MCP.

### Run a single test (headless, no GUI)
```bash
freecadcmd /home/mx/opencaudetest/wireplugin/poc_biarc_sweep.py
```

### Run a single test with segments
```python
exec(open("/home/mx/opencaudetest/wireplugin/test_wirecreator_both.py").read())
```

### Run in FreeCAD GUI console
```python
exec(open("/home/mx/opencaudetest/wireplugin/poc_biarc_sweep.py").read())
```

## Architecture Notes

### Core Module: WireCreator.py
The module provides a `WireCreator` class with these main operations:
- `__init__(min_bend_radius=12.0)` - constructor with configurable minimum bend radius
- `create_wire(segments)` - builds path from segment chain with bi-arc connections
- `check_wire()` - validates bend radius and arc length constraints; returns failed arcs
- `visualize_bad_arcs(diameter=4.0)` - highlights arcs failing constraints
- `make_cable(wire, diameter=4.0)` - sweeps circular profile along path

### Bi-Arc Solver
- Custom Python implementation (no FreeCAD built-in bi-arc solver)
- Computes joint point and two arc segments for G1 continuity
- Falls back to straight line if geometry is degenerate (colinear segments)
- Each bi-arc may be one or two arcs depending on curvature

### Sweep Generation
- Uses `Part.makeCircle` for circular profile
- Uses `Part.Wire.makePipeShell` to sweep profile along path
- Supports Frenet frame for following curvature (default `USE_FRENET=True`)

### Cable Object
- `WireCable.py` defines a persistent `Part::FeaturePython` cable object
- `Points` (`App::PropertyLinkList`) stores ordered start/end node references; nodes can be point references (coordinate systems, Std_Part origins, Parts/Bodies) or `WireBundleSegment` objects
- A bundle segment in a start slot contributes its normal run (`Start` -> `End`); in an end slot it contributes its reversed run (`End` -> `Start`). Picking a bundle segment into an empty slot auto-fills the other node from the segment's `End` reference. `WireCable.execute()` expands each pair into route pieces before calling `WireCreator`
- `Label` is the user-facing wire name; empty names are auto-generated as `wire_<start>_<end>` from the first start and last end reference labels. The owning group label is `<name> Group`
- `Diameter`, `MinBendRadius`, `Length`, `MinimumRadius`, `Status` are stored as properties
- `execute()` rebuilds path and cable geometry from the linked coordinate-system placements
- Linked objects create dependencies, so a document recompute updates moved inputs
- Double-click opens `WireTaskPanel` prefilled with the stored route; edits update the same object
- Path and bad-arc helper objects are linked from `PathObject`, `BadRadiusObject`, `BadLengthObject`
- `Dependencies` (`App::PropertyLinkListGlobal`) stores ancestor GeoFeatureGroups of the point references so moving an enclosing `App::Part`/Body recomputes the cable
- Do not store a link back to the owning group: a group property on the cable creates a `Wire`/`WireCable` dependency cycle. Find the group through `InList` instead.

### Bundle Object
- `WireBundle.py` defines `WireBundle` (`App::FeaturePython`) with `Segments` and `Cables` link lists
- Each `WireBundleSegment` (`Part::FeaturePython`) has `Start`/`End` point references and a `Radius`
- Use `App::PropertyLinkGlobal` for segment start/end references; normal `App::PropertyLink` triggers FreeCAD scope warnings when the referenced objects live inside an `App::Part`
- Segment `execute()` builds a pickable cylinder from the current point placements
- Bundle segments are independent: no bundle-level bi-arcs or segment-to-segment links
- Do not link a segment back to its bundle; the bundle links segments (`Segments`) and the view provider claims them as children
- Implement `attach()` on custom view providers and set `self.Object`; `claimChildren()` can be called after a reload without `__init__`
- `WireBundleSegment` also has hidden `Dependencies` (ancestor groups); update them when segment endpoints change so outer Part moves recompute the segment
- Double-click the bundle to edit its segments; deleting the bundle removes its segments (deferred cleanup)

### Plugin Structure
- Workbench: `WirePluginWorkbench` (registered via `FreeCADGui.addWorkbench()`)
- Toolbar commands: `WirePlugin_CreateWire` (cable) and `WirePlugin_DefineBundle` (bundle segments)
- `WireTaskPanel` provides the segment/point-reference editor and geometry controls
- `WireCable` provides the persistent cable object and double-click editing
- `WireBundle` provides the bundle container and independent straight segment objects
- `WireBundleTaskPanel` defines bundle segments; `PointReference.py` holds shared point-pick helpers
- Installed in `freecad/WirePlugin/` inside the addon

## Setup Requirements

### Prerequisites
- FreeCAD GUI installed and running
- Plugin directory linked to FreeCAD Mod path (e.g., via `.FreeCAD` directory)

### Environment Quirks
- Scripts check `App.GuiUp` before using GUI features; raise `SystemExit` if not available
- FreeCAD objects are created in `App.ActiveDocument`; creates new document if none exists

## Operational Gotchas

### Headless Mode
All scripts handle headless execution by checking `App.GuiUp`. They exit cleanly if GUI is not available.

### Document Cleanup
Scripts remove existing objects with prefix `PoC_`, `WireCreatorTests`, `Test_` before creating new objects to avoid conflicts.

### Visualization
- Bad arcs are shown in red (minimum radius violation) or orange (length violation)
- Cable shown in blue with 20% transparency
- Failed cables have 0% transparency for visibility

### Coordinate System
Segment start/end points can be defined in global coordinates or relative to a Placement/offset. The plugin uses FreeCAD's standard positioning gizmos for editing.

### Selection Gate Cleanup
- Pick mode installs a `Gui.Selection` gate and observer; always remove both after a pick and when the task panel is destroyed.
- Selection-gate `allow()` can receive names or `Document`/`DocumentObject` instances; handle both forms.

### Deletion Cleanup
- Do not remove helper objects or the owning group synchronously inside a ViewProvider `onDelete`; FreeCAD's GUI command recorder can emit a truncated `removeObject(` command. Defer cleanup with `QtCore.QTimer.singleShot(0, ...)` using stored names.

## Conventions

### Naming
- **Segment**: Ordered list of pieces with start/end points
- **Bi-arc**: G1 transition between two segments (computed in Python)
- **Cable**: Result of sweeping circular profile along path
- **Bundle**: Collection of cables routed together (future work)

### Parameters
- `MIN_BEND_RADIUS`: default 12.0 mm (configurable per cable)
- `CABLE_DIAMETER`: default 4.0 mm (configurable)
- `USE_FRENET`: default True (follows curvature when sweeping)

### Test Results
- `check_wire()` returns list of failed arcs with:
  - `label`: human-readable name
  - `failed_tests`: list of test indices that failed (1=radius, 2=length)
  - `biarc_total_len`, `chord_len`, `radius` (if available)

## References
- `freecad/WirePlugin/WireCreator.py` - core bi-arc/path/sweep implementation
- `freecad/WirePlugin/WireCable.py` - persistent cable object, dependency recompute, ViewProvider
- `freecad/WirePlugin/WireTaskPanel.py` - segment editor and geometry controls
- `freecad/WirePlugin/WirePluginCmd.py` - toolbar commands
- `freecad/WirePlugin/WireBundle.py` - bundle/segment objects and cylinder visualization
- `freecad/WirePlugin/WireBundleTaskPanel.py` - bundle segment editor
- `freecad/WirePlugin/PointReference.py` - shared point-reference pick helpers
- `snippet_archive/poc_biarc_sweep.py` - original PoC demonstration
- `snippet_archive/test_wirecreator.py` - archived test suite with predefined segment sets
- `plan.md` - project milestones and terminology
- `diary.md` - development log (minimal)
- `snippet_archive` - earlier isolated tests and classes kept for reference

