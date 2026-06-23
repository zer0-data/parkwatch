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

    hotspots_response = client.get("/api/hotspots?limit=1")
    hotspots_response.raise_for_status()
    hotspots = hotspots_response.json()
    assert hotspots
    cell_id = hotspots[0]["grid_cell_id"]

    weekly_response = client.get(f"/api/timeseries/{cell_id}/weekly")
    weekly_response.raise_for_status()
    weekly = weekly_response.json()
    assert isinstance(weekly, list)

    evidence_response = client.get("/api/model-evidence")
    evidence_response.raise_for_status()
    evidence = evidence_response.json()
    assert evidence["forecast_source"]
    assert "not measured congestion" in evidence["note"].lower()

    copilot_response = client.post(
        "/api/copilot",
        json={
            "question": "Can we claim verified minutes saved from this dashboard?",
            "mode": "analyst",
            "active_tab": "Forecast & Operations: impact",
            "selected_cell_id": cell_id,
            "filters": {},
        },
    )
    copilot_response.raise_for_status()
    answer = copilot_response.json()["answer"].lower()
    assert "verified minutes saved" not in answer
    assert "measured congestion reduction" not in answer

    print("Mappls fallback and evidence smoke test passed")


if __name__ == "__main__":
    main()
