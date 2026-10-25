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

## Milestone 2C: Ferrule Library, Wire Sizes and Color Coding (Follow-up)
Goal: Model real wire-end ferrules from the DIN 46228 T4 data, select standard wire sizes in the cable tool, and support sleeve/insulation color coding.

### Source Data
- Input CSV: `wire_end_sleeves_DIN_46228_T4_complete.csv` in the project directory.
- Input CSV: `cable_colors_DIN47100.csv` for the DIN 47100 insulation color sequence; only single-color entries (numbers 1-10) are currently exposed as cable colors.
- Columns: `cross_section_mm2`, `AWG`, `color_code_DIN`, `color_code_T`, `color_code_W`, `total_legnth_l1_mm`, `l2_mm`, `d1_mm`, `s1_mm`, `d2_mm`, `s2_mm`, `standard`, `Not according to norm`.
- Normalize `total_legnth_l1_mm` to `total_length_l1_mm` in the JSON.
- `L1` is the total ferrule length including the protective plastic sleeve over the wire insulation.
- `L2` is the conductive tip length.
- `d1` is the conductive tip inner diameter; `s1` is its wall thickness.
- `d2` is the protective sleeve inner diameter; `s2` is its wall thickness.
- Cable outer diameter = `d2 - 1.0 mm` unless the user selects a custom wire size.
- The CSV color codes describe the **plastic sleeve only**, using DIN/T/W code systems.
- Preserve the nonconforming flag per row; show it as a warning in the selector.

### Requirements
- [x] **JSON ferrule library**: Convert the CSV into a checked-in JSON file with units, color palette and a cross-section list. Each cross-section carries its color codes and available ferrule entries; each ferrule entry has a geometry `type` (e.g. `tube`), its standard, and one or more property variants.
- [x] **Data converter**: Add a small script to regenerate the JSON from the CSV and validate required fields, units and duplicate variants. It is an example converter; new input formats may need modifications.
- [x] **Wire size selector**: Add a wire-size dropdown to the cable tool populated from the JSON; show cross-section and AWG. Standard sizes derive the cable outer diameter from `d2 - 1.0 mm`; `Custom wire size` keeps the current editable diameter field.
- [x] **Custom wire size**: When `Custom wire size` is selected, show/editable cable diameter and core diameter fields; for standard sizes show the derived diameter/core as read-only/informational.
- [x] **Ferrule tip type**: Add `Ferrule` to the tip-type dropdown in the cable-tip editor.
- [x] **Ferrule type/variant selector**: After selecting a cross-section/AWG, choose the ferrule type (for example `tube`) per tip, then pick one of its variants when several exist. Show the standard carried by the selected ferrule entry. Custom wire sizes do not select a predefined ferrule.
- [x] **Ferrule geometry**: Model the conductive tip as a tube of length `L2`, inner diameter `d1`, wall `s1`; expand through a 45 degree plastic cone until the sleeve diameter is reached; model the colored protective sleeve with inner `d2`, wall `s2`; total length `L1`.
- [x] **Sleeve color**: Select the sleeve color through the DIN/T/W color-code table for the selected wire size; color the plastic sleeve and its cone. The metal tip stays metallic.
- [x] **Wire insulation color**: Add a separate cable-level wire-insulation color selection in the cable tool; keep it independent from the ferrule sleeve color. Options come from the single-color DIN 47100 entries (CSV numbers 1-10).
- [ ] **Yellow-green protective earth**: Render PE insulation as alternating yellow/green bands. Keep the color system extensible for other special wire codings.
- [x] **Stripped length**: The cable's stripped length is the conductive tip length `L2` plus the 45 degree cone length; trim the outer insulation accordingly and expose the core.
- [x] **Core compatibility**: For a predefined cross-section, enforce the corresponding core size. Ferrules are matched to that cross-section and color code. Validate that the core fits inside `d1`.
- [x] **Persistence/recompute (data/menus)**: Store wire size, ferrule type/variant, sleeve color system and cable insulation color on the cable/tips; cable stripping/core geometry recomputes on change.
- [x] **Live tool updates**: Changes to segments/references, wire size, diameters or bend radius update the cable immediately with a short debounce; once more than one segment exists the tool auto-creates the path/cable. Incomplete routes keep the valid prefix visible as the red path (preview mode) and show an orange status message.

### Technical Details
- JSON structure: top-level `schema_version`, `source_csv`, `units`, `color_palette`, and `cross_sections`. Each cross-section has `cross_section_mm2`, `awg`, `color_codes` (DIN/T/W), derived `cable_diameter_mm`, and `ferrules`. Each ferrule entry has `type`, `standard`, and `variants`; each variant contains `l1_mm`, `l2_mm`, `d1_mm`, `s1_mm`, `d2_mm`, `s2_mm`, `conforming` and an optional `note`.
- Keep the CSV as the source of truth and commit the generated JSON under the plugin resources; the converter can be run manually when the CSV changes.
- Color palette mapping: GY grey, BN brown, YE yellow, VT violet, TQ turquoise, PK pink, WH white, OG orange, RD red, BK black, GN green, BU blue, IV ivory, BE beige, OL olive. Use reasonable clearly distinct HTML-style colors in the JSON; exact RGB values are not critical.
- Ferrule dimensions: metal outer diameter = `d1 + 2*s1`; sleeve outer diameter = `d2 + 2*s2`; 45 degree cone length = `(sleeve_outer - metal_outer) / 2`; cone length is included in the `L2` dimension per review; remaining sleeve length = `L1 - L2 - cone_length`, validated to be positive.
- The ferrule metal part and colored sleeve/cone can be separate helper `Part::Feature` objects in the cable group; the exposed conductive core is generated by the existing stripped-tip machinery.
- The cable outer diameter is driven by the ferrule sleeve (`d2 - 1.0 mm`) for standard sizes; standard sizes also enforce the matching core size. Custom wire sizes keep the current diameter/core editing behavior and do not use predefined ferrules.
- The tip panel ferrule page shows the selected size, type/variant, sleeve color preview, tip length (`L1`) and stripped length. The tip length is flagged red with an error when it exceeds the available tip-segment length.
- Ferrule data is loaded by `FerruleData.py`; the cable tool gets the wire-size menu and the tip panel gets ferrule type/variant/sleeve-code menus, a color preview and tip/stripped length. Core size is read from the cable, not edited in the tip panel.
- The UI flow is cross-section/AWG → ferrule type → variant, with the type and standard shown in the selector.
- Yellow-green PE insulation is rendered as alternating yellow/green bands. The color system should remain extensible for other special wire codings.
- Keep the ferrule sleeve/cone color separate from the cable-level wire insulation color in both data and UI. The cable tool exposes DIN 47100 single colors only; double and triple colors from the CSV remain data for future multi-wire coding work.

### Acceptance Criteria
- The JSON library loads and the wire-size dropdown lists all available sizes.
- A standard wire size derives the cable diameter from `d2 - 1.0 mm` and enforces the matching core size; custom size shows/edits the current diameter/core.
- The tip editor can select a cross-section/AWG, ferrule type, variant and DIN/T/W sleeve color.
- Custom wire size lets the user set both cable diameter and core diameter; tool edits update an existing cable live.
- Ferrule geometry shows the metallic conductive tip, 45 degree plastic cone and colored sleeve with dimensions from the data; cone and sleeve share the selected color.
- The cable outer insulation is stripped over `L2 + cone_length`; the exposed core fits `d1` or shows a warning.
- Ferrule sleeve/cone color follows the selected DIN/T/W code; wire insulation color is cable-level and independently selectable.
- Yellow-green PE insulation is shown as alternating bands and is visually distinguishable.
- Changing wire size, ferrule variant or color updates both ends/geometry as applicable.

> **Implementation note:** Wire-size and ferrule menus are populated from the JSON. Ferrule tips now generate the metallic tip, colored plastic cone/sleeve and exposed-core geometry. Cable-level insulation color selection is implemented; yellow-green PE band rendering remains.

### Resolved Decisions
- Cone length is included in the `L2` dimension per review; sleeve length is `L1 - L2 - cone_length`.
- The 45 degree cone is plastic, part of the sleeve, and uses the selected sleeve color.
- Use reasonable HTML-style colors for the code palette; exact RGB values are not critical as long as the colors are clearly distinguishable.
- Yellow-green protective earth uses alternating color bands; the system remains extensible for other special wire codings.
- Selecting a predefined cross-section enforces the matching core size.
- Ferrule variants match the selected cross-section and color code.
- Wire insulation colors are cable-level and independent from the ferrule sleeve/cone color.
- The ferrule standard is stored on each ferrule type entry, not globally.

## Milestone 2D: Tool Transactions and Undo (Follow-up)
Goal: Make tool-session edits reversible as one operation and support normal undo while tools are open.

### Requirements
- [ ] **Tool transaction**: Opening a tool starts a FreeCAD transaction or equivalent snapshot of the affected objects and properties.
- [ ] **Live edits in a session**: Changes inside the tool apply live but remain grouped as one tool-session operation.
- [ ] **Cancel/rollback**: Canceling or closing with revert restores the opening snapshot, including objects created or removed during the session.
- [ ] **Commit as one undo step**: Confirming the tool commits all session edits so a single undo reverts the whole session.
- [ ] **Undo while open**: Normal undo/redo works while the tool is open without leaving partial objects or breaking live updates.
- [ ] **Helpers and renames**: Handle helper-object creation/deletion, group changes, label changes and dependency recomputes.
- [ ] **Recorder safety**: Avoid duplicate objects, transaction-recorder corruption and deferred-deletion conflicts.

### Technical Details
- Wrap tool sessions with `Document.openTransaction` / `commitTransaction` / `abortTransaction` or a session snapshot helper.
- Capture a snapshot when the tool opens and compare/restore on close; commit once on OK.
- Apply live edits within the open transaction; never commit per keystroke or per spin step.
- Coordinate with deferred deletion cleanup and FreeCAD's GUI command recorder.
- Cover the cable tool, tip tool and harness editor with the same session mechanism.

### Acceptance Criteria
- A single undo after a tool session reverts all changes made while the tool was open.
- Cancel restores the previous state, including created/removed helpers and renamed objects.
- Live edits are visible during the session but batched into one undo step.
- Undo/redo leaves no stale or duplicate objects.

## Milestone 2E: Wire Destination and Label Export (Follow-up)
Goal: Store what each cable end connects to and expose that data for wire labeling and label-printer workflows.

### Requirements
- [ ] **Tip destination**: Add a `Destination` property to each `WireTip`, editable in the tip panel; support free-form EN IEC 81346-1 style reference designations.
- [ ] **Cable endpoint metadata**: Show each tip's destination in the cable/tip editor and expose both endpoint destinations for wire lists and labels.
- [ ] **Label data export**: Export wire-label data containing at least wire name, source/destination, cross-section/AWG, insulation/sleeve color and length.
- [ ] **Label-printer workflow**: Export label-ready data (CSV/JSON first, optional ZPL/printer templates later) for selected wires or all wires in a harness.
- [ ] **Persistence/validation**: Preserve destinations across save/reload and warn about missing or duplicate endpoint destinations where useful.

### Technical Details
- Store `Destination` as an `App::PropertyString` on `WireTip`; do not add a tip→cable link.
- Keep EN IEC 81346-1 designations as free text initially; structured parsing can be added later.
- Wire labels can show both ends, for example `wire name`, `source → destination`, and wire/cross-section/color/length metadata.
- Start with a CSV/JSON label export; printer-specific templates (ZPL, etc.) can be layered on top.
- Provide an export entry point from the wire/harness UI and reuse the same data for BOM/wire lists.

### Acceptance Criteria
- Each tip can store an editable destination that persists with the document.
- Wire/tip overviews expose both endpoint destinations.
- Label export includes both endpoint destinations and wire metadata.
- Selecting wires/tips can generate label data suitable for a label printer.

## Milestone 3: Open Bundle Segments / Duct Auto-Routing (Future)
Goal: Support slotted wiring ducts and open channels where cables can enter, leave and branch at arbitrary points along a straight bundle segment.

### Requirements
- [ ] **Open bundle segment type**: Bundle segments can be closed tubes (current behavior) or open slotted ducts; store cross-section/opening dimensions and display duct geometry.
- [ ] **Closest-point attachment**: When a wire starts or ends on an open segment, compute the closest point on its centerline/axis and use that as the entry/exit point instead of the segment endpoints.
- [ ] **Open segment bridging**: When a wire routes between two open segments, compute the shortest valid connecting line between their centerlines; use its endpoints as the bridge start/end and connect with bi-arcs.
- [ ] **Branch-offs**: Support wires joining or leaving the main duct at arbitrary positions; create temporary/virtual branch segments where needed to approach at 90° or another configured angle.
- [ ] **Lane preservation**: Keep per-wire lane offsets through open segments; entry/exit connectors must join the assigned lane.
- [ ] **Auto-routing tool**: Dedicated mode where the user selects open segments and the system computes entry/exit points and bridging pieces, with preview and manual overrides.
- [ ] **Constraints/validation**: Clamp points to segment extents, handle skew/non-intersecting segments, check bend radius, bridge length, clearance and collisions.
- [ ] **Recompute**: Update affected wire paths and temporary connectors when duct geometry, lane layout, routes or constraints change.

### Technical Details
- Add a segment type and duct/slot properties to `WireBundleSegment`; provide open-channel visualization in addition to the current cylinder.
- Use line-segment projection/closest-point math; for two open segments, compute the shortest line between them (constrained to both segment extents).
- Treat entry/exit and 90° branch connectors as temporary/derived route pieces; do not persist them as user-defined bundle segments unless pinned.
- Integrate with the harness lane layout: entry/exit points are offset to the wire's assigned lane.
- Keep auto-routing separate from the manual point/bundle-segment routing workflow as a fallback.
- Preview computed entry/exit points, bridge lines and temporary branches; allow the user to override them.

### Acceptance Criteria
- Can define open slotted bundle segments and see their duct geometry.
- A wire can attach to an open segment at the closest point rather than its endpoints.
- Two open segments connect via the shortest valid bridge, with bi-arcs at both connector ends.
- Wires can branch on/off at arbitrary points, including 90° approaches where required.
- Lane offsets are preserved through open segments and temporary connectors.
- Duct/route/constraint changes recompute affected cables.
- Auto-generated entry/exit points and temporary branches can be previewed and overridden.

## Future Milestones (High-level)
- **M2b**: Dedicated harness pattern and placement editor (patterns, per-segment order, slot editing, preview)
- **M2C**: Ferrule library, data-driven wire sizes and color coding
- **M2D**: Tool transactions and undo for live-edited tool sessions
- **M2E**: Wire destination metadata and label-printer export
- **M3**: Open bundle segments / duct auto-routing (closest-point attachment, shortest bridges, branch-offs)
- **M4**: Cable decomposition (bundle segments → cable-segments per cable with share/branch rules)
- **M5**: Pathfinding/obstacle avoidance, properties (gauge/color), length, BOM, discrete cable lengths, wire loops, cable-clip placeholders, connector lengths, wire endpoint presets, stripped tips/ferrules, flat ribbon cable routing, foamboard manufacturing plans
- **M6**: Polish, docs, packaging

## Milestone 5: Optional/Advanced Features (Notes)
- [ ] **Discrete cable lengths**: Option to specify a cable length (for high-speed cables sold in discrete lengths). Track/flag if routed length differs from specified discrete length.
- [ ] **Wire loops / service loops**: Feature to create wire loops to neatly store extra cable (add slack/loops in route). Configurable loop size/shape.
- [ ] **Cable clip / mounting point placeholders**: Automatically place placeholder objects along the wire length using configurable minimum and maximum spacing so clips or mounting points can be added easily. Segment start and end points are always included; placeholders update when the route changes.
- [x] **Connector lengths and total cable length**: Per-end tip objects store a `LengthOffset` capped by the first/last route-piece length; the visual cable is shortened at each end while `Length` remains the total including tips and `CableOnlyLength` tracks the shortened cable. This supports matching cables where ordering specifications include connector length.
- [ ] **Connector-length drawing (documentation)**: Add an annotated drawing showing an actual cable and what each length number represents: cable-only length, start connector length, end connector length, and total length including connectors.
- [ ] **Foamboard manufacturing plan**: Translate the cable harness into a flat foamboard layout for physical assembly. Show routes, labels, lengths, connector endpoints, and mounting/clip positions, with configurable scale and printable/exportable output (e.g. SVG/DXF, tiled sheets for large boards).
- [ ] **Wire endpoint / conductor editor**: Dedicated menu for editing wire endpoints with presets for US AWG gauge and metric cross-section area, conductor construction (solid, stranded, fine-stranded) for small dimensional variations, and typical insulation thickness. Derive conductor and outer diameters so the swept geometry is dimensionally correct. See M2C for the ferrule data and wire-size selection foundation.
- [x] **Stripped wire tips (initial)**: Tip type with stripped length, wire-level core diameter/area input (mm/mm² unit selector), common 1.0/1.5/2.5 mm² presets shared by both tips, and generated core cylinders limited to the cable diameter.
- [ ] **Ferrules and expanded conductor presets**: Add ferrule geometry and broader AWG/metric conductor presets to the cable-tip panel. M2C covers the initial DIN 46228 T4 library and ferrule rendering.
- [ ] **Flat ribbon cable routing**: Dedicated routing approach for flat ribbon cable with multiple parallel conductors. Constrain bending to one axis, prevent in-plane twisting, support folds (including reverse folds), and generate ribbon width/thickness plus conductor geometry using a fold-aware path model.
- [ ] **Pathfinding/obstacle avoidance**
- [ ] **Properties (gauge/color)**, **BOM**
