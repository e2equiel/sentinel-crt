# EONET Globe Module

## Overview

`EONETGlobeModule` renders a rotating ASCII globe overlaid with coordinates for active natural events reported by NASA's EONET program. The companion `EONETTracker` fetches the 20 most recent events and refreshes them every hour by default.

## Configuration

The module uses shared layout values from `config.CONFIG`, notably `margins`, to anchor the HUD. No module-specific settings are required.

## Data Flow

When the module loads it instantiates `EONETTracker`, immediately fetches the latest events, and schedules hourly updates. Each render pass projects event coordinates onto the globe, draws dashed guidance lines, and tags entries in a HUD list with category-aware colors.

## Display Elements

- Rotating ASCII globe rendered via `ASCIIGlobe`.
- HUD panel listing up to eight recent events with indexed tags, titles, categories, and proximity markers.
- Visual indicators for event locations on the globe, including dashed projections and highlighted markers.
