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
- [ ] **Plugin structure**: FreeCAD addon structure, registration, workbench stub
- [ ] **Basic UI**: Simple toolbar/commands to create/edit a cable route
- [ ] **Cable object**: Custom FreeCAD Document Object for a single cable
- [ ] **Segment model**: Represent chain of segments with start/end points in order
- [ ] **Segment manipulation**: Add/remove/reorder segments; edit segment start/end points
- [ ] **Bi-arc connections**: Define/connect segments with bi-arcs (concept + basic implementation)
- [ ] **Geometry generation**: From segment chain (with bi-arcs) generate circular profile along path for a single cable
- [ ] **ViewProvider**: Visualize cable in 3D view
- [ ] **Integration**: Work well with PartDesign and Assembly workbenches
- [ ] **Connector linking**: Link cable start and/or end points to existing geometry (connectors/parts/features) so they load/attach to those locations
- [ ] **Cable diameter**: Cable diameter must be a user definable parameter
- [ ] **Minimum bending radius**: Minimum bending radius must be a user definable parameter per cable
- [ ] **Bend radius warning**: Throw a warning if the routed path violates the minimum bending radius
- [ ] **Length calculation**: Calculate and display the total cable length

### Technical Details (M1)
- **Objects**: `WireCable` (or `Cable`) Document Object with a property storing ordered list of segments
- **Segment representation**: Each segment = `{start: Vector, end: Vector, ...}`; chain is ordered list; connections use bi-arcs between consecutive segments
- **Coordinate systems**: Segment start/end points must be definable with an offset within a chosen coordinate system. Points can be relative to global, local object, sketch/attachment, or selected reference (to integrate with PartDesign/Assembly).
- **Positioning**: Use FreeCAD's existing positioning gizmos/transform/menu (Placement, Attachment/Map Mode, and standard transform handles) rather than custom drag logic. Allow editing placement/offset via the same UI FreeCAD uses for uniform workflow.
- **Connector linking**: Allow selecting geometry (vertex/face/edge/feature/object) in PartDesign/Assembly and linking it to cable start or end point. When linked, the endpoint's position is driven by that geometry (with optional offset). Handle updates when linked geometry moves.
- **Cable diameter**: A user-definable parameter (e.g., `Diameter` property) for the cable/circular profile. Geometry generation must use this diameter.
- **Minimum bending radius**: A user-definable parameter (e.g., `MinBendRadius` property). Used for validation/warnings.
- **Bend radius checking**: Compute bend radius along the path (bi-arcs/arcs) and warn if any bend radius < MinBendRadius. Warnings visible in UI/property/status.
- **Length calculation**: Compute total length along the path defined by segment chain + bi-arcs (including arc lengths). Display in UI/property (e.g., read-only property or panel display).
- **Commands/UI**: Create cable, edit route (add/move segment endpoints, reorder segments), link/unlink connector to start/end, update geometry, set diameter/MinBendRadius, view total length and bend warnings. Integrate commands into workbench toolbar; leverage FreeCAD selection/attachment.
- **Geometry**: Sweep circle along the path defined by segment chain + bi-arcs to get cable body
- **Workbench**: Minimal workbench with commands for M1 operations, compatible with PartDesign/Assembly contexts

### Acceptance Criteria
- Can create a single cable object in FreeCAD
- Can define a chain of segments with start/end points
- Segment endpoints can be definable with offset in a chosen coordinate system (global/local/attached)
- Moving segment endpoints uses FreeCAD's existing positioning gizmos/transform UI
- Can add/remove/reorder segments and move segment endpoints
- Consecutive segments connect via bi-arcs
- Cable diameter is user definable and used for geometry generation
- Minimum bending radius is user definable
- Warning is displayed if routed path violates minimum bending radius
- Can link cable start/end to existing geometry (connector) and cable attaches to it (with offset support)
- Linked endpoints update when referenced geometry changes position
- Cable geometry (circular cross-section along path) is generated/updated from segment chain
- Total cable length is calculated along the path and displayed
- Basic UI to perform these operations works alongside PartDesign/Assembly workflows

## Milestone 2: Basic Bundle Handling (Focus)
Goal: Handle bundles of cables routed together, with simple arrangement and orientation control.

### Requirements
- [ ] **Bundle object**: Create a bundle Document Object that contains/represents multiple cables
- [ ] **Bundle routing**: Route bundles along a chain of segments (like cables)
- [ ] **Place cables side by side**: For each segment, arrange cables next to each other with a definable gap size
- [ ] **Consistent gaps**: Gaps between cables must be consistent even if cables have different diameters
- [ ] **Cable ordering**: For each segment, cables can be arranged in order and that order must be editable
- [ ] **Per-segment orientation**: Each bundle segment has a position/axis and orientation along the segment axis; users can rotate the arrangement as specified along that axis

### Technical Details (M2)
- **Bundle object**: `WireBundle` Document Object with references to member cables and bundle segment chain
- **Bundle segments**: Bundle has its own ordered segment chain (start/end points). Individual cables follow/are placed relative to bundle path.
- **Arrangement**: For a given bundle segment, compute local cross-section frame (origin on bundle path, axes perpendicular to segment axis). Place each cable in that cross-section based on diameter + gap to neighbors to maintain consistent gap between different diameters.
- **Ordering**: Maintain an ordered list of cables per segment (or per bundle with per-segment overrides). Support reordering in UI.
- **Orientation**: Store orientation angle/rotation about the bundle segment axis for the arrangement on each segment. UI to rotate the cable order/arrangement as specified by the user.
- **Geometry**: Generate geometry for each cable placed in the arranged positions along bundle segments (respecting bi-arcs/transitions)
- **Integration**: Work with PartDesign/Assembly, use FreeCAD positioning/gizmos where applicable

### Acceptance Criteria
- Can create a bundle containing multiple cables
- Bundle follows a chain of segments with start/end points
- Cables are placed side by side on each segment with a definable gap
- Gap is consistent between cables regardless of different cable diameters
- Cable order per segment is editable
- Bundle segment orientation (rotation about segment axis) can be set and changed by user
- Arrangement updates correctly when segment order/orientation/gap/cable diameters change

## Future Milestones (High-level)
- **M3**: Cable decomposition (bundle segments → cable-segments per cable with share/branch rules)
- **M4**: Pathfinding/obstacle avoidance, properties (gauge/color), length, BOM, discrete cable lengths, wire loops
- **M5**: Polish, docs, packaging

## Milestone 4: Optional/Advanced Features (Notes)
- [ ] **Discrete cable lengths**: Option to specify a cable length (for high-speed cables sold in discrete lengths). Track/flag if routed length differs from specified discrete length.
- [ ] **Wire loops / service loops**: Feature to create wire loops to neatly store extra cable (add slack/loops in route). Configurable loop size/shape.
- [ ] **Pathfinding/obstacle avoidance**
- [ ] **Properties (gauge/color)**, **BOM**
