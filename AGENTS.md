# AGENTS.md - VibeWire FreeCAD Cable/Harness Plugin

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
`WireCreator` provides:
- `create_wire(segments)` — builds a path from a straight-segment chain with bi-arc transitions.
- `check_wire()` — validates bend radius and arc-length constraints; returns failed arcs.
- `visualize_bad_arcs(diameter=4.0)` — creates temporary red/orange bad-arc display objects.
- `make_cable(wire, diameter=4.0)` — sweeps a circular profile for a single-color cable.
- `make_cable_sectors(wire, diameter=4.0)` — builds four longitudinal sector solids for multi-color cables.

### Bi-Arc Solver
- Custom Python implementation; no FreeCAD built-in bi-arc solver.
- Shared low-level arc/bi-arc primitives live in `WirePathMath.py`.
- `WireCreator` and `WireTransitions` are the path-building entry points and use the same primitives.
- Computes a joint point and one or two arc segments for G1 continuity.
- Falls back to a straight line when the geometry is degenerate or colinear.
- `WireCable` uses the shared primitives between consecutive bundle-segment runs.

### Shared Geometry, Route and Layout Modules
- `WireGeometry.py` — canonical unit-vector policy, 2D convex hull/centroid, circle sampling, rigid 2D fit.
- `WireTypes.py` — object type predicates and role constants; avoids importing the object layer from pure modules.
- `WireFrames.py` — segment basis, averaged reference axes and manual orientation roll.
- `WireRoute.py` — cable route parsing, harness route graph, facing endpoints and the `segment|cable` layout codec.
- `WireLayout.py` — circular/linear/packed/packed-bundle layout policy; returns a `LayoutResult` with positions, hulls, placements, radii and overlay wires.
- `WirePacking.py` — optional pymunk physics and generic shape packing only.
- `WireReducedDisplay.py` — reduced hulls, prism solids, bi-arc transition solids and RMF frames.
- `WireBundle.py` — persistent harness/segment objects, layout application, groups, display visibility and view providers. Layout computation is delegated to `WireLayout`; reduced geometry to `WireReducedDisplay`.

### Sweep Generation
- Uses `Part.makeCircle` for the profile and `Part.Wire.makePipeShell` for the sweep.
- Frenet framing is used by default (`USE_FRENET=True`).
- Single-color cables use one swept tube; multi-color cables use four sector solids with per-face `ShapeAppearance`.

### Cable Object
- `WireCable.py` defines a persistent `Part::FeaturePython` cable object.
- `Points` (`App::PropertyLinkListGlobal`) is now the ordered list of bundle segments defining the route. Point-to-point route pieces are no longer supported; legacy routes fail validation with a rebuild message.
- `SegmentDirections` (`App::PropertyIntegerList`) stores 0/1 per route segment for normal/reversed traversal.
- `WireCable.execute()` resolves each route row into one oriented bundle run before calling `WireCreator`.
- `Label` is the user-facing wire name; empty names are generated from the first effective start endpoint and last effective end endpoint, including route direction. The owning group label is `<name> Group`.
- `Harness` (`App::PropertyLinkGlobal`) points to the harness that computes lane offsets. Cables link the harness; never link a group back to a cable (that creates a dependency cycle).
- Stored properties include `Diameter`, `WireSizeMM2`, `CoreSizeMode`, `CoreArea`, `CoreDiameter`, `MinBendRadius`, `Length`, `CableOnlyLength`, `MinimumRadius`, `Status`, `Preview`, `CableColor` and `CableColorTracer`.
- `WireSizeMM2` is 0 for custom sizes; standard sizes enforce the matching core area and derive cable diameter from the ferrule sleeve (`d2 - 1 mm`).
- `CableColor` is the primary color enum and `CableColorTracer` is the tracer enum (`None` for solid). Available colors are Black, Brown, Red, Orange, Yellow, Green, Blue, Dark Blue, Violet, Grey, White, Pink and Turquoise.
- The PE shortcut sets primary Green and tracer Yellow. A non-`None` tracer uses three primary quadrants and one tracer quadrant. Multi-color cables use four longitudinal sector solids; single-color cables use the normal swept tube.
- `MaxCables` is enforced per route segment: if any used bundle segment exceeds its limit, the cable fails validation. 0 means unlimited; endpoint segments can be set to 1.
- Core size is wire-level and shared by both tips. Tips are edited through the cable’s `InList`; there is no tip→cable link.
- `StartTip`/`EndTip` link to per-end `WireTip` objects. Tip `LengthOffset` trims visible geometry while `Length` remains total.
- Cable-tool edits live-update after a short debounce. One valid bundle segment is enough to create a cable. Incomplete routes keep the valid prefix in `Points`, set `Preview=True` (red path only), and show an orange status.
- The wire tool keeps a selection observer while open: selecting a bundle segment in 3D selects its row, and selecting a row highlights its bundle segment.
- `execute()` rebuilds geometry from the bundle segment endpoints and depends on ancestor groups of those endpoints.
- Lace helper segments use option A: each cable computes backward/forward chord directions at every helper and rotates the helper path piece by the normalized average. This removes most of the bend waviness while the bi-arc solver handles the gaps.
- Double-clicking a cable opens `WireTaskPanel` prefilled with the stored route; edits update the same object.
- Path, bad-arc, core and ferrule display objects are linked through `PathObject`, `BadRadiusObject`, `BadLengthObject`, `StartCoreObject`/`EndCoreObject`, and `StartFerruleMetal`/`EndFerruleMetal`/`StartFerruleSleeve`/`EndFerruleSleeve`.
- `Dependencies` stores ancestor `GeoFeatureGroup`s of the bundle-segment endpoint references so moving an enclosing `App::Part`/Body recomputes the cable.
- Do not store a link back to the owning group; find it through `InList`.

### Cable Tip Object
- `WireTip.py` defines `WireTip` (`App::FeaturePython`) with `TipType` (`Length offset`/`Stripped wire`/`Ferrule`), `LengthOffset`, `StrippedLength`, `FerruleType`, `FerruleVariant`, `FerruleColorSystem` and `End`.
- Tips are created in the owning cable group and linked through `StartTip`/`EndTip`; they find the cable through `InList`.
- Double-click a tip to open `WireTipTaskPanel`; core size lives on the cable and applies to both tips.
- `LengthOffset`/`StrippedLength` are capped below the first/last route piece length using `TIP_OFFSET_MARGIN = 0.01 mm`; the tip panel applies live and restores previous values on cancel.
- Stripped-wire tips set the outer cable back by `StrippedLength`; core helpers display copper-colored cylinders along the end pieces.
- Ferrule tips use the JSON variant: metallic tip, colored plastic cone/sleeve, and exposed core over `L2 + cone`. Sleeve color comes from the selected DIN/T/W code. `L1` is validated against the available tip-segment length.
- Enabling a ferrule tip selects the shortest conforming variant for the current cross-section/type. Switching cross-section resets ferrule tips to the new size’s shortest conforming variant; if none conform, the shortest available variant is used.
- Tip view providers add a dynamic `Transparency` view property and sync it to the core/ferrule helpers.
- Tip view providers add an empty Coin display mode and set `DefaultMode=0` so the no-shape tip is showable; otherwise the tree eye remains grey.
- Locate the tip mode switch through `ViewObject.RootNode`; `ViewObject.SwitchNode` can raise `No SWIG wrapped library loaded` after proxy reloads.
- `listDisplayModes()` is a shared registry, so check the actual mode-switch child count before adding `Default`.
- Clicking a core/ferrule helper remaps selection to the owning tip; hidden helper rows never pop into the tree.
- A single queued selection reconciler reads `Gui.Selection`, restores canonical helper materials, preserves helper transparency, and highlights all helpers of selected tips.
- Helper materials use neutral ambient colors and preserve current transparency. Clearing selection also clears stale tree selection/current/background state.
- Opening a wire, tip or harness tool re-selects the edited object (or the selected segment for the harness) after FreeCAD enters edit mode.
- Closing a tool deselects only the edited object, clears its current-item/background state, and leaves other selected objects selected.

### Harness Object
- `WireBundle.py` defines `WireHarness` (`App::FeaturePython`, proxy type `WireHarness`) with `Segments`, `SegmentGroup`, `CableOrder`, `Gap`, `Pattern` (`Circular`/`Linear`/`Packed`/`Packed Bundles`) and computed `Layout`.
- `WireLayout.py` computes the layout; `WireBundle` applies the returned positions, hulls, placements and radii to the document objects.
- `Packed` uses the optional pymunk 2D physics engine in `WirePacking.py`: a loose spiral seed is compacted into a touching cross-section with zero wire clearance; the packed offsets are shifted so the smallest-enclosing-circle center coincides with the segment axis, and segment display radius uses that circle. For branched harnesses, segments are processed from lowest to highest cable count; each cable is seeded from lower-count neighbours' projected entry points, higher-count neighbours are ignored, and adjacent segments with identical cable sets copy their section. U-turn joins transfer the neighbour's cross-section coordinates through travel-frame alignment instead of raw 3D projection. `Packed Bundles` builds each incoming lower-count bundle's convex hull (with a small skin margin), packs those hull polygons (with a SAT separation pass), then copies the source bundle's per-cable offsets into the packed hull centers for a coarser but branch-preserving layout. Hull bodies are free to rotate in the simulation; their final angles are applied to both the copied cable offsets and the drawn hull outlines. The harness `Gap` applies only to `Circular`/`Linear`. If pymunk is unavailable, the harness falls back to `Circular` and the harness panel shows a warning notice.
- Cables link `cable.Harness`; the harness finds member cables through `InList` and never links them back.
- `Layout` stores lane offset vectors keyed by `segmentName|cableName`; cables shift both bundle-run endpoints by their offset. The harness also computes each segment's `HullCurve` from the cable offsets and diameters for later covering/exit work.
- Each `WireBundleSegment` (`Part::FeaturePython`) has `Start`/`End` point references, `Radius`, `Orientation`, `MaxCables` (0 = unlimited), `SegmentRole` (`Route`/`Lace Helper`) and a computed, hidden `HullCurve` (closed convex hull of the bundle at the segment start).
- For `Packed Bundles`, the harness draws outline overlays on the segment start faces: green `Bundle Hulls` (per incoming bundle hulls used by the packing) and orange `Overall Hull` (one hull around all segment cables). Both are harness-linked `Part::Feature` objects, non-selectable, claimed in the tree, and cleared for other patterns.
- `DisplayMode` (`Full Detail` default, `Reduced Bundle`) controls harness drawing and is only applied to the `Packed Bundles` pattern; other patterns force Full Detail. `Reduced Bundle` hides cables, tips, support helpers, lace helpers and hull overlays, and draws one prism per segment from a hierarchical convex hull built from octagon cable approximations (hull of lower-segment hulls at merges). It also sweeps the smaller-count segment hull along the bi-arc path from the facing endpoint selected by the cable route to the same hull transformed by the larger segment's Packed Bundles placement (position and rotation) on the larger end face. Hull copies are placed at 20° arc intervals; each copy's normal follows the negated path tangent via a rotation-minimizing frame, with a linear roll correction so the final copy matches the packing frame. Consecutive copies connect vertex `i` to vertex `i` with explicit triangles. Sections use the same vertex order, so the longitudinal lines stay one-to-one; the larger segment's hull naturally covers the join. `ReducedBundleObject` is a harness-linked, non-selectable `Part::Feature`; the harness editor exposes the mode dropdown and resets it to Full Detail for other patterns.
- New segments default to visible, dark grey (`0.33, 0.33, 0.36`) at 65% transparency. The selected segment’s display radius is live-editable; Add Segment copies the active/default radius.
- Route segments are placed in the `SegmentGroup`; lace helpers and their point nodes are placed in the separate `HelperGroup` (`Lace Helpers`). The harness claims both groups in the tree, so each eye toggles its own contents.
- The harness view provider has an empty Coin display mode and `DefaultMode=0` so its eye/claimed children are showable.
- Bundle segments occasionally receive a Part view provider with `Proxy=None` and no Coin display modes; `execute()` initializes it with `ViewObject.Proxy=1`, makes it visible, and signals the tree icon.
- Use `App::PropertyLinkGlobal` for segment start/end references; normal `PropertyLink` triggers scope warnings inside `App::Part`.
- `Segment.execute()` builds a pickable cylinder from the current point placements.
- Bundle segments are independent: no bundle-level bi-arcs or segment-to-segment links.
- Do not link a segment back to its harness; the harness links segments and the view provider claims the segment group.
- `Dependencies` stores ancestor groups of the segment endpoints so outer Part moves recompute segments.
- Double-click a harness to edit its segments; deleting the harness removes its segment group and segments via deferred cleanup.
- The harness editor list and 3D selection sync in both directions. Opening the harness editor from a segment selects its row and preserves the segment selection.

### Plugin Structure
- Workbench: `VibeWireWorkbench`, registered with `FreeCADGui.addWorkbench()`. The Python package path is `freecad.VibeWire`.
- Toolbar commands: `VibeWire_CreateWire` and `VibeWire_DefineHarness`.
- Context-menu commands: cables offer Edit Wire/Start Tip/End Tip; tips offer Edit Tip; bundle segments offer Edit Harness plus Move Start/End Point (transform gizmo with `Std_Placement` fallback); harnesses offer Edit Harness.
- Workbench task watchers populate the Tasks panel contextually: Create, Wire Tools, Tip Tools, Bundle Tools, Harness Tools.
- Wire/Tip/Bundle task-watcher entries are custom hover buttons. Hovering does not change selection: cable hover turns the cable green, tip hover highlights helpers or shows a temporary green tube for an offset tip’s route end, and bundle Move Start/End shows an opaque green cap face plus circular edge.
- `WireTaskPanel` is bundle-segment-only: one picker per route row and Reverse Segment; one valid segment auto-creates the cable.
- `WireCable` provides the persistent object and double-click editing.
- `WireHarness` is the layout authority and owns the straight segment objects.
- `WireBundleTaskPanel` edits harness route segments, visibility group, per-segment radius/MaxCables, gap, pattern and display mode; it excludes auto-generated lace helpers from the editor list, rebuilds them on Update Harness, syncs list/3D selection, notes that `Packed` uses zero clearance, and warns when `Packed` is selected without pymunk.
- `WireLayout.py` owns layout policy; `WireGeometry.py`, `WireFrames.py`, `WireRoute.py` and `WirePathMath.py` are the shared core helpers.
- `WireReducedDisplay.py` builds the reduced-bundle prisms and transitions; `WireBundle.py` applies visibility and display objects.
- `WireBendHelpers.py` rebuilds sparse lace helpers from the solved bends; `VibeWire_RegenerateLaceHelpers` is the toolbar/context command.
- `WireColors.py` holds the primary/tracer palette and quadrant logic.
- `WirePacking.py` provides the optional pymunk-backed `Packed` harness layout and pymunk availability checks.
- `FerruleData.py` loads the checked-in ferrule JSON.
- `WireSelection.py` provides the selection reconciler, helper remapping and hover previews.
- `WireTaskWatchers.py` defines the contextual Tasks-panel groups and hover buttons.
- Installed from `freecad/VibeWire/` inside the addon; the user-facing addon/package name is `VibeWire`.

## Setup Requirements

### Prerequisites
- FreeCAD GUI installed and running.
- Plugin directory linked into the FreeCAD Mod path.
- Optional: `pymunk` for the `Packed` harness pattern (`pip install --user pymunk` using FreeCAD's Python). Without it, `Packed` falls back to `Circular` and the harness panel warns.

### Environment Quirks
- FreeCAD runs as an AppImage with its own Python environment.
- Use the FreeCAD MCP bridge for all FreeCAD Python execution; do not use the host Python.
- Scripts check `App.GuiUp` before using GUI features and should exit cleanly when headless.
- FreeCAD objects are created in `App.ActiveDocument`; create a document when none exists.
- Workbench/task-watcher changes require restarting FreeCAD or reloading the workbench and task watcher modules.

## Operational Gotchas

### Headless Mode
Scripts handle headless execution by checking `App.GuiUp` and exit cleanly when GUI is unavailable.

### Document Cleanup
Tests remove objects with prefixes `PoC_`, `WireCreatorTests`, and `Test_` before creating new objects.

### Visualization
- Bad arcs are red for minimum-radius violations and orange for length violations.
- Cable color comes from `CableColor`/`CableColorTracer`; new cables are solid (`Transparency=0`) and user-set transparency is preserved across recomputes.
- Failed cables use 0% transparency.
- Hover previews use temporary green overlay geometry and remove it on leave; the preview object is hidden from the tree.
- Bundle segments default to visible dark grey at 65% transparency.

### Coordinate System
Bundle segment endpoints are point references defined in global coordinates or relative to a Placement/offset. The plugin uses FreeCAD’s standard positioning gizmos.

### Selection and Tree Hygiene
- Helper clicks remap to the owning tip; do not leave helper rows selected.
- `WireSelection` reconciles tip/helper appearance from the current document selection rather than incremental callbacks.
- Clear tree selection/current/background only when the final selection is empty; avoid clearing tree state synchronously during row-to-row selection changes.
- Tool open/close preserves unrelated selections and removes only the edited object.

### Selection Gate Cleanup
- Pick mode installs a `Gui.Selection` gate and observer; remove both after a pick and when the task panel is destroyed.
- Selection-gate `allow()` can receive names or `Document`/`DocumentObject` instances; handle both.
- Wire editing uses the bundle-segment-only gate; the harness editor uses the point-reference gate.

### Deletion Cleanup
- Do not remove helper objects, segment groups, or the owning group synchronously inside a ViewProvider `onDelete`; FreeCAD’s command recorder can emit a truncated `removeObject(` command. Defer cleanup with `QtCore.QTimer.singleShot(0, ...)` using stored names.

### View Provider Initialization
- No-shape `App::FeaturePython` objects need an empty Coin display mode and `DefaultMode=0` for the tree eye to be active.
- New `Part::FeaturePython` bundle segments can arrive with `ViewObject.Proxy=None` and zero display modes; initialize `Proxy=1`, make them visible and call `signalChangeIcon()`.
- Do not rely on `ViewObject.SwitchNode` after proxy reloads; use `RootNode` and find the `SoSwitch`.

## Conventions

### Naming
- **Route segment / bundle segment**: A straight segment with start/end point references; bundle segments are the required wire-path building block. Rename TODO is tracked in `plan.md`.
- **Route**: Ordered list of bundle segments with per-segment Normal/Reversed directions.
- **Bi-arc**: G1 transition between two route runs.
- **Cable**: Swept circular result of a route.
- **Harness/Bundle**: Collection of cables and the segment layout authority.
- **PE**: Protective earth shortcut (primary Green, tracer Yellow).

### Parameters
- `MIN_BEND_RADIUS`: default 12.0 mm, configurable per cable.
- `CABLE_DIAMETER`: default 4.0 mm.
- `USE_FRENET`: default True.
- `MaxCables`: default 0 (unlimited); set 1 on endpoint segments.
- Display radius: default 10.0 mm per bundle segment.

### Test Results
- `check_wire()` returns failed arcs with:
  - `label`
  - `failed_tests` (1 = radius, 2 = length)
  - `biarc_total_len`, `chord_len`, `radius` when available.

## References
- `freecad/VibeWire/WireCreator.py` — bi-arc/path/sweep and sector profile implementation.
- `freecad/VibeWire/WirePathMath.py` — shared arc, bi-arc and path primitives.
- `freecad/VibeWire/WireGeometry.py` — shared 2D geometry and fitting helpers.
- `freecad/VibeWire/WireFrames.py` — segment coordinate frames and orientation.
- `freecad/VibeWire/WireRoute.py` — route graph, route parsing and layout codec.
- `freecad/VibeWire/WireLayout.py` — layout policy and `LayoutResult`.
- `freecad/VibeWire/WireReducedDisplay.py` — reduced-bundle display geometry.
- `freecad/VibeWire/WireTypes.py` — shared object predicates and role constants.
- `freecad/VibeWire/WireCable.py` — persistent cable object, validation, colors and helpers.
- `freecad/VibeWire/WireTaskPanel.py` — bundle-segment wire route editor and geometry controls.
- `freecad/VibeWire/VibeWireCmd.py` — toolbar and context-menu commands.
- `freecad/VibeWire/WireBundle.py` — harness/segment objects, layout application, route/helper groups and view providers.
- `freecad/VibeWire/WireBendHelpers.py` — automatic sparse lace-helper generation and orientation interpolation.
- `freecad/VibeWire/WireBundleTaskPanel.py` — harness segment/group/radius/gap/pattern/display-mode editor.
- `freecad/VibeWire/WireTip.py` — per-end cable tip settings object and view provider.
- `freecad/VibeWire/WireTipTaskPanel.py` — cable tip settings editor.
- `freecad/VibeWire/FerruleData.py` — ferrule JSON loader and helpers.
- `freecad/VibeWire/WireSelection.py` — selection reconciler, helper remapping and hover previews.
- `freecad/VibeWire/WireTaskWatchers.py` — contextual Tasks-panel tool groups and hover buttons.
- `freecad/VibeWire/WireColors.py` — primary/tracer cable color palette and quadrant layouts.
- `freecad/VibeWire/WirePacking.py` — optional pymunk-backed `Packed` harness layout.
- `freecad/VibeWire/Resources/Data/ferrules_DIN46228_T4.json` — checked-in ferrule library.
- `freecad/VibeWire/PointReference.py` — shared point-reference pick helpers and selection gates.
- `tools/csv_to_ferrules_json.py` — example ferrule CSV-to-JSON converter.
- `plan.md` — milestones and pending naming TODO.
- `diary.md` — development log.
- `snippet_archive/` — earlier isolated tests and classes kept for reference.
