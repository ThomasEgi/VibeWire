# diary.md - minimalistic log of problems, solutions and decisions

- 2026-10-24: Started plugin structure - added Init/InitGui/workbench + command to run test_wirecreator.py via button. Linked plugin dir to FreeCAD Mod. Workbench loads as WirePluginWorkbench, test button works.
- 2026-10-24: Fixed loading the Workbench on FreeCAD startup by changing the project directory structure.
- 2026-10-24: Set the workbench icon to Resources/Icons/wire_icon.png. Added the "Create Wire" task panel: segment list with add/remove/reorder and buttons to pick Part/PartDesign coordinate systems as segment start/end points.
- 2026-10-24: Integrated the PoC WireCreator into the plugin. The task panel now has diameter and minimum bend radius inputs plus "Create Path"/"Create Cable" buttons, creating a Wire group with path, swept cable and highlighted bad bi-arcs.
- 2026-10-24: Added persistent WireCable (Part::FeaturePython) with linked segment coordinate systems, diameter/min bend properties, computed length/status and path/bad-arc helper objects. Double-click reopens the prefilled editor and edits update the same object; link dependencies recompute the cable when inputs move.
- 2026-10-24: Made the start/end coordinate-system names in the task panel clickable to select and reveal the referenced object in the scene.
- 2026-10-24: Extended point references from LCS/PartDesign coordinate systems to Std_Part origins, Parts and PartDesign Bodies so their placement gizmos can drive cable points.
- 2026-10-24: Fixed a Wire group <-> WireCable dependency cycle caused by the stored Container link. The group is now found via InList; legacy links are removed on load/edit, and deleting the cable also removes its path/bad-arc helpers and empty group.
- 2026-10-24: Hardened pick-mode cleanup: gate/observer are removed when the panel is destroyed, `allow()` accepts names or Document/DocumentObject instances, and support-object shapes are purged after update to avoid "still touched after recompute" warnings.
- 2026-10-24: Deferred cable/helper/group deletion cleanup to the next event-loop turn. Synchronous removal inside onDelete corrupted FreeCAD's GUI command recorder (truncated removeObject command) when deleting the Wire group.
- 2026-10-24: Added a wire name field. Empty names auto-fill as `wire_<start>_<end>` from the first segment start and last segment end reference labels; the group label follows the wire name.
- 2026-10-24: M4 reminder: add an annotated drawing showing cable-only length, start/end connector lengths, and total length including connectors.
- 2026-10-24: Counted connector linking as initially done: connector geometry is placed under the same App::Part as the referenced segment point; a dedicated attachment workflow remains future work.
