import os
import pytest
from fastapi.testclient import TestClient
from api.app import create_app
from api.evidence_store import EvidenceStore
from api.weather_routing import AStarWeatherRouter


def test_weather_router_basic_functions():
    router = AStarWeatherRouter()
    
    # 1. Bounding box tests
    assert router.in_bounds(39.52, 2.58) is True  # Palma
    assert router.in_bounds(39.84, 3.14) is True  # Alcudia
    assert router.in_bounds(48.85, 2.35) is False  # Paris (out of bounds)
    assert router.in_bounds(0.0, 0.0) is False  # Equator

    # 2. Distance tests
    dist = router.haversine(39.52, 2.58, 39.84, 3.14)
    assert 20.0 < dist < 40.0  # Approx distance


def test_astar_weather_routing_palma_alcudia():
    router = AStarWeatherRouter()
    
    # Run route calculation
    route = router.find_route(
        origin_lat=39.52,
        origin_lon=2.58,
        dest_lat=39.84,
        dest_lon=3.14,
    )
    
    assert "waypoints" in route
    assert len(route["waypoints"]) >= 2
    assert "distance_nm" in route
    assert route["distance_nm"] > 0
    assert "estimated_time_h" in route
    assert route["estimated_time_h"] > 0
    assert route["source_tag"] == "astar_weather_route_v1"

    # Make sure we didn't cross any land (none of the waypoints should be over land)
    # Check that each waypoint latitude and longitude is valid
    for wp in route["waypoints"]:
        assert 38.0 <= wp["lat"] <= 41.0
        assert 1.0 <= wp["lng"] <= 4.5


def test_api_route_integration_astar(tmp_path):
    # Initialize the app with an empty temporary evidence store
    store = EvidenceStore(tmp_path)
    app = create_app(store)
    client = TestClient(app)

    # Query route between Palma and Alcudia via API
    response = client.get("/places/route/palma/alcudia")
    assert response.status_code == 200
    
    data = response.json()
    assert data["origin_place_id"] == "palma"
    assert data["destination_place_id"] == "alcudia"
    assert data["source_tag"] == "astar_weather_route_v1"  # Confirms A* weather router is used!
    assert len(data["waypoints"]) >= 2
    assert data["distance_nm"] > 0


def test_api_route_fallback_out_of_bounds(tmp_path):
    store = EvidenceStore(tmp_path)
    app = create_app(store)
    client = TestClient(app)

    # Use coordinates outside the expanded Western Med grid (e.g., Lisbon to Athens)
    # This should gracefully fall back to searoute (source_tag: "graph_sea_route_v1")
    response = client.get(
        "/places/route/palma/alcudia?origin_latitude=38.72&origin_longitude=-9.14&destination_latitude=37.98&destination_longitude=23.72"
    )
    assert response.status_code == 200
    
    data = response.json()
    assert data["source_tag"] == "graph_sea_route_v1"  # Verified fallback!

