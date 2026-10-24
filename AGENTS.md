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

### Run WireCreator test (plugin test button)
The plugin's "Run WireCreator Test" command executes `test_wirecreator.py` and prints results for two test segment sets (good and failure cases).

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

### Plugin Structure
- Workbench: `WirePlugin` (registered via `Gui.addWorkbench()`)
- Commands: `RunWireTestCommand`, `CreateCableCommand`
- Installed in `FreeCAD_WirePlugin/` directory
- `CableTaskPanel` provides UI for cable creation

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
- `WireCreator.py` - core implementation
- `poc_biarc_sweep.py` - demonstration with random segment generation
- `test_wirecreator.py` - test suite with predefined segment sets
- `plan.md` - project milestones and terminology
- `diary.md` - development log (minimal)
- `snippet_archive` - contains some more or less isolated tests and classes which we may want to integrate into the actual plugin code at some point

