# FreeCAD Wire/Cable Routing Plugin - Project Plan

## Terminology
- **Wire/Cable**: Interchangeable terms. A cable is a circular object following a defined path.
- **Bundle**: A collection of cables routed together.
- **Segment**: A piece of the path between two endpoints. Wires/cables/bundles are routed along a chain of segments.
- **Bi-arc**: Segments are connected by bi-arcs.
- **Cable-segment**: A segment that belongs to an individual cable (derived from bundle segments or defined directly).
- **Top-down approach**: Define bundle segments first → break down to cable-segments → generate geometry.
- **Connector**: A part/feature/face/vertex/edge that can be loaded as a start/end point of a cable.

## Operation Model
- Cables/bundles are routed as a chain of individual segments.
- Each segment has a start point and an end point.
- Segments are connected using bi-arcs (smooth transitions between segments).
- A bundle's route defines the shared path structure; individual cables can share segments of a bundle, branch off, or join back between segments.
- Top-down: create/define bundle segments (path framework), decompose into cable-segments per cable, then create geometry from cable-segments.
- Cable endpoints can be linked to geometry (connectors) so the cable attaches/load at those locations.

## Proof of Concept (PoC) - Before M1
Goal: Test core functions programmatically before integrating into FreeCAD UI/workbench.

### Requirements
- [x] **Test setup**: Simple script runnable in FreeCAD (Python/FreeCAD console)
- [x] **Two segments**: Define two segments numerically in code (start/end points with known coordinates)
- [x] **Bi-arc calculation**: Compute bi-arcs connecting the two segments, preferably using FreeCAD internal solvers. Only hand-code math if absolutely necessary
- [x] **Path construction**: Build the full path as segment - arc - arc - segment (bi-arc connection)
- [x] **Sweep geometry**: Extrude/sweep a circle along the resulting path to create cable geometry
- [x] **Validation output**: print() total path length and minimum bending radius

### Technical Details (PoC)
- **Input**: Hardcoded values for two segments (e.g., vectors/points). Example: segment 1 from P0 to P1, segment 2 from P2 to P3 with a gap/change in direction
- **Bi-arc solver**: Use FreeCAD/Part/Draft APIs where possible (e.g., Part.BSplineCurve, curve construction, or built-in methods). Investigate curve tangencies/bi-arc fitting via FreeCAD internals
- **Path**: Construct composite curve (edge/wire) representing segment1 + bi-arc(s) + segment2
- **Sweep**: Create a circle profile (Part.makeCircle) and sweep along the wire/path (Part.Wire.makePipeShell or sweep)
- **Metrics**: Calculate length (edge/wire length) and minimum curvature/bend radius along arcs (1/curvature). Print results
- **Deliverable**: A standalone FreeCAD script (e.g., `poc_biarc_sweep.py`) demonstrating the above

### Acceptance Criteria
- Script runs in FreeCAD console without errors
- Two numeric segments are defined
- Bi-arcs connecting them are computed (using FreeCAD solvers where possible)
- Circle is swept along the resulting path producing valid geometry
- print() shows total length and minimum bending radius

## Milestone 1: Single Cable, Basic UI, Segment Manipulation (Focus)
Goal: Get the core model working for a single cable before handling bundles/multi-cable logic.

### Requirements
- [x] **Plugin structure**: FreeCAD addon structure, registration, workbench stub
- [x] **Basic UI**: Simple toolbar/commands to create/edit a cable route
- [x] **Cable object**: Custom FreeCAD Document Object for a single cable, storing its segment references and geometry parameters
- [x] **Segment model**: Represent chain of segments with start/end points in order
- [x] **Segment manipulation**: Add/remove/reorder segments; edit segment start/end points
- [x] **Edit existing cable**: Double-click a created cable in the tree to reopen the segment editor with its stored segments and parameters; apply changes to the same cable instead of creating a new one
- [x] **Recompute on input changes**: Recompute path and cable geometry automatically when referenced coordinate systems or linked geometry move, plus a manual recompute option
- [x] **Bi-arc connections**: Define/connect segments with bi-arcs (concept + basic implementation)
- [x] **Geometry generation**: From segment chain (with bi-arcs) generate circular profile along path for a single cable
- [x] **ViewProvider**: Visualize cable in 3D view
- [x] **Integration**: Work well with PartDesign and Assembly workbenches
- [x] **Connector linking (initial)**: Link cable start/end points to existing geometry by placing connector geometry under the same App::Part as the referenced segment point; a dedicated connector-attachment workflow can follow later
- [x] **Cable diameter**: Cable diameter must be a user definable parameter
- [x] **Minimum bending radius**: Minimum bending radius must be a user definable parameter per cable
- [x] **Bend radius warning**: Throw a warning if the routed path violates the minimum bending radius
- [x] **Length calculation**: Calculate and display the total cable length
- [x] **Wire naming**: User can enter a wire name; empty names auto-fill as `wire_<first start>_<last end>` using the point-reference labels

### Technical Details (M1)
- **Objects**: `WireCable` (or `Cable`) Document Object with a property storing ordered list of segments
- **Segment representation**: Each segment = `{start: Vector, end: Vector, ...}`; chain is ordered list; connections use bi-arcs between consecutive segments
- **Persistent cable data**: Store the ordered segment/point references (coordinate systems, Std_Part origins, Parts/Bodies), diameter and minimum bend radius as properties on the cable object so the route survives closing the editor and saving/reloading the document
- **Point references**: Segment start/end points must be definable with an offset within a chosen reference. Supported references include Part/PartDesign coordinate systems, Std_Part origins, and Part/Body placements. Points can be relative to global, local object, sketch/attachment, or selected reference (to integrate with PartDesign/Assembly).
- **Positioning**: Use FreeCAD's existing positioning gizmos/transform/menu (Placement, Attachment/Map Mode, and standard transform handles) rather than custom drag logic. Allow editing placement/offset via the same UI FreeCAD uses for uniform workflow.
- **Edit existing cable**: The cable ViewProvider exposes double-click (and an edit command) that reopens the segment editor prefilled from the cable's stored data. Edits update the existing cable object and its geometry in place; no duplicate path/cable objects.
- **Recompute/dependencies**: Reference coordinate systems and linked geometry through link properties so `Document.recompute()` re-evaluates the cable. The cable's `execute()` rebuilds path and swept geometry from current input placements. Provide a manual "Recompute Wire" fallback.
- **Connector linking**: Allow selecting geometry (vertex/face/edge/feature/object) in PartDesign/Assembly and linking it to cable start or end point. When linked, the endpoint's position is driven by that geometry (with optional offset). Handle updates when linked geometry moves. Current initial approach: place connector geometry under the same App::Part as the referenced segment point, so it moves with that point.
- **Cable diameter**: A user-definable parameter (e.g., `Diameter` property) for the cable/circular profile. Geometry generation must use this diameter.
- **Minimum bending radius**: A user-definable parameter (e.g., `MinBendRadius` property). Used for validation/warnings.
- **Bend radius checking**: Compute bend radius along the path (bi-arcs/arcs) and warn if any bend radius < MinBendRadius. Warnings visible in UI/property/status.
- **Length calculation**: Compute total length along the path defined by segment chain + bi-arcs (including arc lengths). Display in UI/property (e.g., read-only property or panel display).
- **Naming**: Provide a name field. When left empty, generate `wire_<first start label>_<last end label>` from the first start and last end references; use the same sanitized string as the internal object name.
- **Commands/UI**: Create cable, edit route (add/move segment endpoints, reorder segments), link/unlink connector to start/end, update geometry, set diameter/MinBendRadius, view total length and bend warnings. Integrate commands into workbench toolbar; leverage FreeCAD selection/attachment.
- **Geometry**: Sweep circle along the path defined by segment chain + bi-arcs to get cable body
- **Workbench**: Minimal workbench with commands for M1 operations, compatible with PartDesign/Assembly contexts

### Acceptance Criteria
- Can create a single cable object in FreeCAD
- Can define a chain of segments with start/end points
- Segment endpoints can be definable with offset in a chosen coordinate system (global/local/attached)
- Moving segment endpoints uses FreeCAD's existing positioning gizmos/transform UI
- Can add/remove/reorder segments and move segment endpoints
- Can double-click a created cable to reopen the segment editor with its current segments and parameters
- Applying editor changes updates the same cable object and its geometry without creating duplicates
- Moving a referenced coordinate system updates the cable geometry on document recompute
- Consecutive segments connect via bi-arcs
- Cable diameter is user definable and used for geometry generation
- Minimum bending radius is user definable
- Warning is displayed if routed path violates minimum bending radius
- Can link cable start/end to existing geometry (connector); initial approach uses the App::Part placement of the referenced segment point
- Linked endpoints update when referenced geometry changes position
- Cable geometry (circular cross-section along path) is generated/updated from segment chain
- Total cable length is calculated along the path and displayed
- Wires have an identifiable `wire_<start>_<end>` name, auto-generated from the first start and last end when no name is entered
- Basic UI to perform these operations works alongside PartDesign/Assembly workflows

## Milestone 2: Basic Bundle Handling (Focus)
Goal: Handle bundles of cables routed together, with simple arrangement and orientation control.

### Requirements
- [x] **Harness object**: Create a harness Document Object containing a collection of independent straight bundle segments, member cables and the computed cable layout
- [x] **Bundle segments**: Define every bundle segment by start/end point references (same reference types as M1); bundle segments have no bi-arcs or physical interconnections and each provides a pickable cylindrical display geometry
- [x] **Mixed wire routing**: Give each cable an ordered route that can mix precise point-to-point segments (M1 style) with bundle-segment references; a bundle segment picked as start runs normal, picked as end runs reversed, and routes may use subsets of the bundle and branch in/out
- [x] **Pickable bundle segments**: Pick bundle segment cylinders for a wire segment start or end instead of entering point endpoints; picking auto-fills the other node from the bundle segment (start runs normal, end runs reversed)
- [x] **Wire-level bi-arcs**: Generate transitions between consecutive route pieces with the M1 bi-arc solver; the bundle itself remains straight segments only
- [x] **Place cables side by side**: For each bundle segment, arrange routed cables with a definable gap using a linear or circular cross-section pattern
- [x] **Consistent gaps**: Edge-to-edge gaps remain consistent even with different cable diameters in the linear pattern; the circular pattern uses a clearance-based ring radius
- [x] **Per-segment orientation**: Rotation of the cable arrangement about the bundle segment axis is user-definable per segment
- [x] **Bundle segment display**: Show pickable cylinder geometry for each bundle segment (with a configurable preview radius)
- [x] **Recompute**: Update affected cable routes/geometry when segment point references, route direction, cable order, gap or cable diameters change

### Technical Details (M2)
- **Harness object**: `WireHarness` Document Object with a `Segments` link list of `WireBundleSegment` objects, a `CableOrder` string list, a `Gap`, and a computed `Layout` map. It does not build a connected path. Member cables are discovered through `harness.InList` (cables link `cable.Harness`); the harness must not store cable links, to avoid dependency cycles.
- **Bundle segments**: Each `WireBundleSegment` is an independent straight segment defined by `Start` and `End` point references using the M1 point-reference types. It has no link to neighbouring segments and therefore no bi-arcs. Each segment also exposes a pickable cylinder aligned with its axis for 3D selection; its radius can be a configurable preview or derived from the per-segment arrangement.
- **Wire route (current)**: Each wire row has a start and end node; either node may be a point reference or a `WireBundleSegment`. A bundle segment picked as start contributes its normal run (`Start` -> `End`); picked as end it contributes its reversed run (`End` -> `Start`). Mixed rows expand into route pieces (bundle runs plus direct connections), and a route containing only point nodes is the M1 standalone cable.
- **Picking and direction**: The wire panel start/end pickers accept point references and bundle segment cylinders. Picking a bundle cylinder into an empty start/end slot auto-fills the other node with the segment's `End` reference, so one pick defines a complete run: start uses the segment normal (`Start` -> `End`), end uses it reversed (`End` -> `Start`). If both slots are already set, they form a mixed route between the chosen nodes; explicit per-entry direction toggles can be added later.
- **Segment frame**: For a segment axis `u = normalize(end - start)`, derive a lateral axis from the averaged global coordinate frames of the `Start`/`End` references (local Z, then Y/X fallbacks), then apply the segment's `Orientation` angle about `u`. This preserves rotations of the driving LCS/App::Part/Body frames, with manual roll composed on top. The cable uses the same lateral axis for its lane offset.
- **Arrangement (current)**: The harness has a `Pattern` enum (`Circular` by default, or `Linear`). Linear places centres along the lateral axis using edge-to-edge spacing `r_i + gap + r_(i+1)` and centres the row on the segment axis. Circular distributes centres at equal angles around the axis, choosing a ring radius large enough for the requested adjacent clearance. The harness stores the resulting 2D/3D offset vectors in `Layout` keyed by `segmentName|cableName`; exact circular gap packing and per-segment order overrides can be added later.
- **Offset segments**: For a cable on a segment, the lane offset is constant along the straight segment. The cable reads the harness-computed global offset vector from `cable.Harness.Layout` and shifts both endpoints by that vector. Normal direction: `start = segment.start + offset`, `end = segment.end + offset`, tangent `+u`. Reversed direction: `start = segment.end + offset`, `end = segment.start + offset`, tangent `-u`.
- **Bi-arc generation**: Resolve every route row into ordered route pieces (bundle runs plus direct connections). Feed the pieces to the M1 `WireCreator`, which inserts bi-arcs between consecutive pieces; gaps and reversals are handled at cable level, not bundle level.
- **Branching**: A cable may route over any ordered subset of bundle segments. Per-segment member lists are derived from the cables' routes, so cables can join or leave the bundle between segments without changing the bundle segment definitions.
- **Geometry/recompute**: The harness is upstream of its cables: cables link `cable.Harness`, while the harness finds cables through `InList` and never links them. Harness layout depends on segment geometry and cable order/gap/diameter; cable changes touch the harness explicitly. Segments and cables also keep hidden ancestor-group dependencies so moving an enclosing `App::Part`/Body recomputes them. Recomputing follows segments -> harness layout -> cables -> paths/sweeps/validation.
- **UI**: Harness editor for adding/removing segments, picking start/end references, setting gap, pattern and per-segment rotation. Cable route editor for adding point-pair entries or picking bundle segment cylinders, with reordering and branching; direction is implied by the start/end slot (start normal, end reversed). The harness claims its segments and cable groups in the tree. Advanced pattern/placement editing is deferred to M2b.
- **Integration**: Use the same point-reference model as M1 so bundle segments can be driven by PartDesign/Assembly geometry and standard placement gizmos.

### Acceptance Criteria
- Can create a harness containing multiple independent straight segments
- Bundle segments are defined by start/end references and have no bundle-level bi-arcs or forced interconnections
- Can assign a cable to an ordered mixed route of direct segments and bundle segments with `Normal`/`Reversed` directions
- Can pick a bundle segment cylinder as a wire start (normal) or end (reversed), with the other node auto-filled from the segment
- Direct precise segments and bundle segments can be mixed in the same cable route
- Cable routes can use subsets of the bundle and branch in/out
- Bi-arcs are generated at the cable level between consecutive route pieces, including direct/bundle transitions
- Cables are arranged in a definable gap using either the circular or linear harness pattern
- Linear patterns keep edge-to-edge gaps consistent for different diameters; circular patterns keep at least the requested clearance
- The harness computes lane offsets and cables read them from the harness
- Cable changes (route, diameter, harness membership) invalidate and recompute the harness layout
- Per-segment arrangement orientation can be set and changed
- Updating segment references, routes, order, gap or diameters recomputes affected cable geometry

> **Scope note:** Basic circular/linear patterns and manual per-segment rotation are in M2. The dedicated pattern and placement editor is tracked separately in Milestone 2b.

## Milestone 2b: Harness Pattern & Placement Editor (Follow-up)
Goal: Provide a dedicated editor for the growing set of cable pattern and placement options without expanding basic M2.

### Requirements
- [ ] **Pattern library**: Support linear rows, circular rings, multi-row/grid layouts and custom placement patterns
- [ ] **Pattern editor**: Choose pattern per harness and per bundle segment; configure origin/anchor, rotation, gap and spacing rules
- [ ] **Cable placement**: Edit per-segment cable order and per-segment overrides; reorder cables in a cross-section preview
- [ ] **Slot editing**: Assign cables to explicit slots/offsets with constraints and clearance checks
- [ ] **Mixed diameters**: Clearance-aware packing and warnings for circular and 2D patterns with different cable diameters
- [ ] **Preview**: 2D cross-section preview in the task panel and optional 3D lane preview
- [ ] **Persistence/recompute**: Store pattern settings and slot assignments; recompute all affected cables on change

### Technical Details
- Extend `WireHarness`/`WireBundleSegment` with pattern settings and per-segment overrides; do not add cable back-links
- Keep layout computation in the harness; store final offsets/slots as plain data/global vectors
- Build a dedicated 2D cross-section editor for the selected segment
- Use deterministic ordering and stable slot IDs so editing remains predictable
- Add clearance/packing checks; circular patterns must account for mixed diameters
- Keep the simple `Pattern` property (`Circular`/`Linear`) as the M2 baseline; M2b generalizes it

### Acceptance Criteria
- Can choose and edit a pattern per harness and per bundle segment
- Can edit per-segment cable order and explicit cable slots/offsets
- Mixed-diameter cables maintain requested clearance or show warnings
- Pattern/placement changes recompute all affected cable geometry
- Pattern and placement settings persist across save/reload

## Future Milestones (High-level)
- **M2b**: Dedicated harness pattern and placement editor (patterns, per-segment order, slot editing, preview)
- **M3**: Cable decomposition (bundle segments → cable-segments per cable with share/branch rules)
- **M4**: Pathfinding/obstacle avoidance, properties (gauge/color), length, BOM, discrete cable lengths, wire loops, cable-clip placeholders, connector lengths, wire endpoint presets, stripped tips/ferrules, flat ribbon cable routing, foamboard manufacturing plans
- **M5**: Polish, docs, packaging

## Milestone 4: Optional/Advanced Features (Notes)
- [ ] **Discrete cable lengths**: Option to specify a cable length (for high-speed cables sold in discrete lengths). Track/flag if routed length differs from specified discrete length.
- [ ] **Wire loops / service loops**: Feature to create wire loops to neatly store extra cable (add slack/loops in route). Configurable loop size/shape.
- [ ] **Cable clip / mounting point placeholders**: Automatically place placeholder objects along the wire length using configurable minimum and maximum spacing so clips or mounting points can be added easily. Segment start and end points are always included; placeholders update when the route changes.
- [ ] **Connector lengths and total cable length**: Allow entering a connector length for both cable ends. Track the cable-only length separately from the total length including connectors, with distinct names such as `CableLength` (path only) and `TotalLengthWithConnectors` (path + both connector lengths), so the value can be matched against cable ordering specifications that include connector length.
- [ ] **Connector-length drawing (documentation)**: Add an annotated drawing showing an actual cable and what each length number represents: cable-only length, start connector length, end connector length, and total length including connectors.
- [ ] **Foamboard manufacturing plan**: Translate the cable harness into a flat foamboard layout for physical assembly. Show routes, labels, lengths, connector endpoints, and mounting/clip positions, with configurable scale and printable/exportable output (e.g. SVG/DXF, tiled sheets for large boards).
- [ ] **Wire endpoint / conductor editor**: Dedicated menu for editing wire endpoints with presets for US AWG gauge and metric cross-section area, conductor construction (solid, stranded, fine-stranded) for small dimensional variations, and typical insulation thickness. Derive conductor and outer diameters so the swept geometry is dimensionally correct.
- [ ] **Stripped tips and ferrules**: Automatically generate the smaller core-only tip at each wire endpoint with configurable strip length, and optionally generate ferrule geometry (length/diameter/color by wire size) for connector-ready ends.
- [ ] **Flat ribbon cable routing**: Dedicated routing approach for flat ribbon cable with multiple parallel conductors. Constrain bending to one axis, prevent in-plane twisting, support folds (including reverse folds), and generate ribbon width/thickness plus conductor geometry using a fold-aware path model.
- [ ] **Pathfinding/obstacle avoidance**
- [ ] **Properties (gauge/color)**, **BOM**
