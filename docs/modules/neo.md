# NEO Tracker Module

## Overview

`NeoTrackerModule` visualizes the closest near-earth object reported by NASA's NEO feed. It renders a rotating vector sphere, asteroid trajectory, solar system map, and heads-up display of approach details.

## Configuration

- `nasa_api_key` must be populated so the `NEOTracker` can authenticate with the NASA API.
- Layout and typography rely on shared values such as `margins` and theme colors from `config.CONFIG`.

## Data Flow

During load the module creates a `NEOTracker`, which immediately fetches the next seven days of objects and schedules refreshes every six hours. Each render pass pulls the cached closest approach data and drives the various visualizations.

## Display Elements

- Animated vector sphere with dashed or solid asteroid path segments based on depth.
- Heads-up display that summarizes the object's name, diameter, velocity, approach date, miss distance, and hazard assessment.
- Solar system mini-map showing planetary orbits and the object's projected trajectory relative to Earth.
