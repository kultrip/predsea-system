# PredSea Route Waypoint Endpoint Design

## Goal
Add a maritime route geometry endpoint that returns waypoint coordinates for a route between two places, with optional raw latitude/longitude overrides on day one.

This endpoint must stay aligned with PredSea's canonical place registry and route-distance logic. It should use the `searoute` Python library to generate a navigable sea path and expose the path as ordered waypoints.

## User-Facing API

### Endpoint
`GET /places/route/{origin}/{destination}`

### Query parameters
- `origin_latitude` and `origin_longitude` optional
- `destination_latitude` and `destination_longitude` optional

### Resolution rules
1. If origin latitude/longitude are provided, use them.
2. Otherwise resolve `{origin}` via the canonical place registry.
3. If destination latitude/longitude are provided, use them.
4. Otherwise resolve `{destination}` via the canonical place registry.
5. If a side cannot be resolved, return a clear 422 error.

### Response shape
```json
{
  "origin_place_id": "palma",
  "origin_place_name": "Palma",
  "origin_latitude": 39.56,
  "origin_longitude": 2.63,
  "destination_place_id": "ibiza",
  "destination_place_name": "Ibiza",
  "destination_latitude": 38.91,
  "destination_longitude": 1.45,
  "distance_nm": 100.0,
  "estimated_time_h": 6.25,
  "waypoints": [
    { "lat": 39.56, "lng": 2.63 },
    { "lat": 39.40, "lng": 2.40 },
    { "lat": 39.10, "lng": 2.05 },
    { "lat": 38.91, "lng": 1.45 }
  ],
  "source_tag": "graph_sea_route_v1",
  "computed_at_utc": "2026-06-17 12:00 UTC"
}
```

## Implementation Approach

### Shared resolver
Add a small shared route resolver in the API layer that:
- resolves place IDs through the canonical place registry
- accepts coordinate overrides when provided
- normalizes both inputs into a single origin/destination point structure

### Geometry engine
Use `searoute` to compute the route geometry and nautical distance.
- The output should be converted into a simple list of `{lat, lng}` waypoints.
- The distance should be returned in nautical miles.
- Estimated travel time should be derived from the route length and a default planning speed, unless the library provides a reliable duration directly.

### Fallback behavior
- If the route library cannot produce a valid maritime path, return a clear error rather than inventing a straight line.
- If only place resolution succeeds and no coordinates are available, still fail gracefully with a 422.
- If the geometry library raises on a malformed route, surface a controlled API error and keep the existing distance endpoints unchanged.

## Non-Goals
- Do not replace the existing `/places/distance` contract.
- Do not change the weighted optimal route solver.
- Do not add weather sampling or route intelligence to this endpoint.
- Do not invent waypoints when the sea routing library cannot produce them.

## Testing
Add tests that cover:
- place ID only resolution
- raw coordinate overrides on day one
- mixed place/coordinate requests
- missing resolution inputs returning 422
- route geometry returning a waypoint list
- route geometry failure returning a controlled error

## Docs
Update the API README and the WhatsApp/API usage docs so the route waypoint endpoint is visible alongside:
- `/places/distance`
- `/places/distance/coordinates`
- `/routes/optimal/{origin}/{destination}`

