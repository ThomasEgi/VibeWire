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
- `Points` (`App::PropertyLinkListGlobal`) stores ordered start/end node references; nodes can be point references (coordinate systems, Std_Part origins, Parts/Bodies) or `WireBundleSegment` objects. Use the global list type so references inside `App::Part` scopes do not trigger warnings
- A bundle segment in a start slot contributes its normal run (`Start` -> `End`); in an end slot it contributes its reversed run (`End` -> `Start`). Picking a bundle segment clears both fields first, then sets the clicked slot to the segment and the other slot to the segment's opposite endpoint; this redefines the whole segment instead of leaving stale references. `WireCable.execute()` expands each pair into route pieces before calling `WireCreator`
- `Label` is the user-facing wire name; empty names are auto-generated as `wire_<start>_<end>` from the first start and last end reference labels. The owning group label is `<name> Group`
- `Harness` (`App::PropertyLinkGlobal`) points to the harness that computes this cable's lane offsets
- `Diameter`, `WireSizeMM2`, `CoreSizeMode`, `CoreArea`, `CoreDiameter`, `MinBendRadius`, `Length`, `CableOnlyLength`, `MinimumRadius`, `Status` and `Preview` are stored as properties
- `WireSizeMM2` is 0 for custom wire sizes; standard sizes enforce the matching core area and derive the cable diameter from the ferrule sleeve (`d2 - 1 mm`)
- `CableColor` is the primary cable-level `App::PropertyEnumeration`; `CableColorTracer` is the tracer enumeration (`None` for solid). `apply_cable_color()` maps them to the cable's `ShapeColor`/`ShapeAppearance`
- The cable tool has separate primary and tracer dropdowns. Primary choices include PE, Black, Brown, Red, Orange, Yellow, Green, Blue, Dark Blue, Violet, Grey, White, Pink and Turquoise; tracer choices are `None` plus the same colors
- Selecting the PE shortcut sets primary Green and tracer Yellow. A non-`None` tracer uses three primary quadrants and one tracer quadrant. Multi-color cables are built from four longitudinal sector solids and colored per face; single-color cables keep the normal swept tube
- Core size is wire-level and shared by both tips; the tip panel edits the cable through `InList` without adding a tip→cable link
- `StartTip`/`EndTip` link to per-end `WireTip` settings objects; tip `LengthOffset` shortens the visible geometry, while `Length` remains the total and `CableOnlyLength` is the shortened value
- Cable changes to `Points`, `Diameter` or `Harness` touch the harness so the lane layout is recalculated upstream
- Cable-tool edits (segments, wire size, diameter, core, bend radius) live-update after a short debounce; with more than one segment the tool auto-creates the cable. Incomplete routes keep the valid prefix in `Points`, set `Preview=True` (red path only) and show an orange status message
- The wire tool keeps a selection observer while open: selecting a bundle segment in 3D selects its row, and selecting a row highlights its bundle/point references
- `execute()` rebuilds path and cable geometry from the linked coordinate-system placements
- Linked objects create dependencies, so a document recompute updates moved inputs
- Double-click opens `WireTaskPanel` prefilled with the stored route; edits update the same object
- Path, bad-arc, core and ferrule helper objects are linked from `PathObject`, `BadRadiusObject`, `BadLengthObject`, `StartCoreObject`/`EndCoreObject` and `StartFerruleMetal`/`EndFerruleMetal`/`StartFerruleSleeve`/`EndFerruleSleeve`
- `Dependencies` (`App::PropertyLinkListGlobal`) stores ancestor GeoFeatureGroups of the point references so moving an enclosing `App::Part`/Body recomputes the cable
- Do not store a link back to the owning group: a group property on the cable creates a `Wire`/`WireCable` dependency cycle. Find the group through `InList` instead.

### Cable Tip Object
- `WireTip.py` defines `WireTip` (`App::FeaturePython`) with `TipType` (`Length offset`/`Stripped wire`/`Ferrule`), `LengthOffset`, `StrippedLength`, `FerruleType`, `FerruleVariant`, `FerruleColorSystem` and `End` (`Start`/`End`)
- Tips are created in the owning cable group and linked from the cable through `StartTip`/`EndTip`
- Tips do not link back to the cable; they find it through `InList`
- Double-click a tip to open `WireTipTaskPanel`; core size lives on the cable and applies to both tips. Ferrule and expanded conductor presets can be added there later
- Cable geometry is trimmed from the route ends by the tip settings; `Length` remains full and `CableOnlyLength` subtracts only connector-style length offsets (stripped conductor keeps the cable length)
- `LengthOffset`/`StrippedLength` are capped to just below the first/last route-piece length (`StartTipLength`/`EndTipLength` minus `TIP_OFFSET_MARGIN` = 0.01 mm); the tip panel applies changes live and restores the previous values on cancel
- Stripped-wire tips set the outer cable back by `StrippedLength`; `StartCoreObject`/`EndCoreObject` display copper-colored core cylinders along the end pieces, clamped to the cable diameter
- Ferrule tips use the selected JSON variant: the cable builds a hollow metallic tip, a colored plastic cone and sleeve, and the exposed core over `L2 + cone`. Sleeve color comes from the selected DIN/T/W code. Ferrule `L1` is validated against the tip-segment length and flagged in the tip panel when too long.
- Enabling a ferrule tip selects the shortest conforming variant for the current cross-section/type; switching the cable cross-section resets ferrule tips to the shortest conforming variant for the new size. If no variant is marked conforming, the shortest available variant is used.
- Clicking a core/ferrule helper remaps the selection to its owning `WireTip`; helper rows stay hidden. A single queued selection reconciler then restores canonical helper materials and applies the green highlight to all helpers of the selected tips.
- The reconciler reads `Gui.Selection` after any selection event instead of clearing/applying highlights incrementally; this avoids callback-order races when switching between tips. Helper materials preserve current transparency, use neutral ambient colors, and are recomputed from cable/tip data. Clearing the selection also clears stale tree selection/current/background state.
- Opening a wire, tip or harness tool re-selects the edited object after FreeCAD enters edit mode; a selected tip therefore keeps its helper geometry highlighted.
- Closing a wire, tip or harness task panel deselects only the object edited by that tool, clears its shortened tree current-item highlight and any stale selection background, and leaves separately selected objects selected.
- Toggling a tip's eye icon syncs visibility of its core/ferrule helper geometry; toggle it in the ViewProvider `onChanged`/`attach` handler.
- Tip view providers add a `Transparency` view property and sync it to the tip's core/ferrule helper geometry, matching the cable transparency behavior.
- Tip view providers add an empty Coin display mode and set `DefaultMode=0` so FreeCAD treats the no-shape tip as showable; otherwise the tree eye icon stays grey even when `Visibility` is true.
- Locate the tip's mode switch through `ViewObject.RootNode` (find the child `SoSwitch`); after a view-provider proxy reload, `ViewObject.SwitchNode` can raise `No SWIG wrapped library loaded`.
- `listDisplayModes()` is a shared mode-name registry, so check the actual mode-switch child count before adding the tip's `Default` display mode.

### Harness Object
- `WireBundle.py` defines `WireHarness` (`App::FeaturePython`, proxy type `WireHarness`) with `Segments`, `CableOrder`, `Gap`, `Pattern` (`Circular`/`Linear`) and a computed `Layout` map
- Cables link the harness through `cable.Harness`; the harness finds member cables through `InList` and never links them back (that would create a dependency cycle)
- `Layout` stores lane offset vectors (`x,y,z`) keyed by `segmentName|cableName`; cables read their offset directly and shift both bundle-run endpoints
- Each `WireBundleSegment` (`Part::FeaturePython`) has `Start`/`End` point references, a `Radius` and an `Orientation` (roll about the segment axis)
- The lateral arrangement axis is derived from the averaged global rotations of the start/end reference frames, then rotated by the segment `Orientation`; manual roll composes on top of the input rotation
- Use `App::PropertyLinkGlobal` for segment start/end references; normal `App::PropertyLink` triggers FreeCAD scope warnings when the referenced objects live inside an `App::Part`
- Segment `execute()` builds a pickable cylinder from the current point placements
- Bundle segments are independent: no bundle-level bi-arcs or segment-to-segment links
- Do not link a segment back to its harness; the harness links segments (`Segments`) and the view provider claims them as children
- Implement `attach()` on custom view providers and set `self.Object`; `claimChildren()` can be called after a reload without `__init__`
- `WireBundleSegment` also has hidden `Dependencies` (ancestor groups); update them when segment endpoints change so outer Part moves recompute the segment
- Double-click the harness to edit its segments; deleting the harness removes its segments (deferred cleanup)

### Plugin Structure
- Workbench: `WirePluginWorkbench` (registered via `FreeCADGui.addWorkbench()`)
- Toolbar commands: `WirePlugin_CreateWire` (cable) and `WirePlugin_DefineHarness` (harness segments/gap)
- Context-menu commands: selected cables offer Edit Wire/Start Tip/End Tip; selected tips offer Edit Tip; selected bundle segments offer Edit Harness plus Move Start/End Point (selects the underlying node and opens Std_Placement); selected harnesses offer Edit Harness
- Workbench task watchers populate the Tasks panel contextually: Create tools with no selection, Wire Tools for a cable, Tip Tools for a tip, Bundle Tools for a segment, and Harness Tools for a harness
- `WireTaskPanel` provides the segment/point-reference editor and geometry controls
- `WireCable` provides the persistent cable object and double-click editing
- `WireHarness` provides the layout authority and independent straight segment objects
- `WireBundleTaskPanel` defines the harness and its segments; `PointReference.py` holds shared point-pick helpers
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
- Cable color comes from `CableColor`; new cables are created solid (`Transparency=0`) and user-set transparency is preserved across recomputes
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
- `freecad/WirePlugin/WireBundle.py` - harness layout, segment objects and cylinder visualization
- `freecad/WirePlugin/WireBundleTaskPanel.py` - harness segment/gap/pattern editor
- `freecad/WirePlugin/WireTip.py` - per-end cable tip settings object
- `freecad/WirePlugin/WireTipTaskPanel.py` - cable tip settings editor
- `freecad/WirePlugin/FerruleData.py` - JSON ferrule library loader and helpers
- `freecad/WirePlugin/WireSelection.py` - remaps core/ferrule helper selection to the owning tip
- `freecad/WirePlugin/WireTaskWatchers.py` - contextual task-panel tool groups
- `freecad/WirePlugin/Resources/Data/ferrules_DIN46228_T4.json` - ferrule library
- `freecad/WirePlugin/WireColors.py` - cable color palette and primary/tracer quadrant layouts
- `tools/csv_to_ferrules_json.py` - example CSV-to-JSON converter
- `freecad/WirePlugin/PointReference.py` - shared point-reference pick helpers
- `snippet_archive/poc_biarc_sweep.py` - original PoC demonstration
- `snippet_archive/test_wirecreator.py` - archived test suite with predefined segment sets
- `plan.md` - project milestones and terminology
- `diary.md` - development log (minimal)
- `snippet_archive` - earlier isolated tests and classes kept for reference

