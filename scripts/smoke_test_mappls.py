from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.main import app


def main() -> None:
    os.environ.pop("MAPPLS_REST_KEY", None)
    client = TestClient(app)
    payload = {
        "candidates": [
            {
                "grid_cell_id": "demo-a",
                "latitude": 12.9716,
                "longitude": 77.5946,
                "location": "Demo stop A",
                "predictedViolations": 10,
                "forecastPriority": 80,
                "obstructionRisk": 70,
            },
            {
                "grid_cell_id": "demo-b",
                "latitude": 12.9766,
                "longitude": 77.5993,
                "location": "Demo stop B",
                "predictedViolations": 8,
                "forecastPriority": 75,
                "obstructionRisk": 65,
            },
        ]
    }

    response = client.post("/api/mappls/patrol-plan", json=payload)
    response.raise_for_status()
    data = response.json()
    assert data["route_mode"] == "haversine_fallback"
    assert data["routing_source"] == "Haversine fallback"
    assert len(data["stops"]) == 2
    assert len(data["segments"]) == 1
    assert "MAPPLS_REST_KEY" in data["fallback_reason"]
    assert "d145d9793fc3e58bfc0f2a86a3ceed13" not in str(data)
    delay_response = client.post(
        "/api/mappls/delay-exposure",
        json={**payload, "scenario_reduction": 0.2},
    )
    delay_response.raise_for_status()
    delay = delay_response.json()
    assert delay["items"]
    assert delay["total_delay_exposure_minutes"] > 0
    assert "d145d9793fc3e58bfc0f2a86a3ceed13" not in str(delay)
    print("Mappls fallback smoke test passed")


if __name__ == "__main__":
    main()
