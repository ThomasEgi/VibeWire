> **TL;DR:** A mostly vibe coded FreeCAD workbench for routing cables along reusable segments, insulation colors, and configurable cable tips. **Very much work in progress! Looking for feedback**

# WirePlugin for FreeCAD

WirePlugin is a FreeCAD workbench for modeling cable harnesses by routing wires along reusable straight bundle segments. Cables are built from ordered segment runs with per-segment direction, harness lane offsets, and configurable cable ends.

## Concept

Bundle segments define the physical path framework. A cable is an ordered list of bundle segments, with each segment running either normal or reversed. A harness groups segments and calculates how member cables are arranged along them. Each cable end is configured independently with a tip for length offsets, stripped wire, or ferrules.

## Features

- Persistent cable objects with editable routes and live tool updates
- Bundle-segment-only cable routes with per-segment Normal/Reversed direction
- One bundle-segment picker per route row and a Reverse Segment control
- Hard per-segment `MaxCables` limit, with optional endpoint limits
- Harness lane layouts using circular or linear patterns with configurable gap
- Per-segment display radius, rotation, visibility group, and endpoint transforms
- Wire-size selection driven by the bundled DIN 46228 T4 ferrule library
- Custom diameter and core-size input
- Cable color selection with independent primary and tracer colors
- Multi-color cable cross-sections using four quadrants
- Protective-earth shortcut: Green primary with Yellow tracer
- Tip types for length offset, stripped wire, and ferrules
- Ferrule type, variant, sleeve color code, and tip-length validation
- Automatic shortest-conforming ferrule selection
- Cable length, cable-only length, minimum bend radius, and bend warnings
- Preview mode for incomplete routes
- Two-way selection synchronization between editors and the 3D view
- Contextual Tasks-panel tools for cables, tips, harnesses, and bundle segments
- Hover previews for cables, tips, path segments, and bundle endpoints
- Tip visibility and transparency controls for helper geometry
- Persistent document state across save and reload

## History

Originally I only planned to tinker around with opencode (they allow you to waste some tokens on reasonably capable models) and freecad-mcp, curious how well it would solve something like connecting to line segments with bi-arcs without getting into the math myself. Turned out to be done in a blink. I threw 10 bucks at deepseek using the flash 1017 model and put a bunch of milestones down, blasting through them at breakneck speed. stuff got implemented as fast as i could come up with ideas for improvements. two days and 8 bucks into the token budget thinks look pretty good. lots of desirable features and a not so horrible workflow. Still plenty of things to do but it could already do a decent job on some projects. If you want to get a feeling for how things progressed, i let the ai write a diary.md. It's not a 1-line-per-promt but it hardly took more than 3 or 4 promts to get from one to the next. The plan.md still has a bunch of open  points for the future ( mostly exporting, naming, some ux improvements, etc). Lots will change, so don't use it for production yet.
