from fastapi import HTTPException

import backend.main as main


PREDICTION = {"success": True, "predicted_connectivity_score": 82.5}
ANOMALY = {"success": True, "anomaly": False}


def test_combined_ai_analysis_returns_both_results(client, monkeypatch):
    monkeypatch.setattr(main, "ai_prediction", lambda: PREDICTION)
    monkeypatch.setattr(main, "ai_anomaly", lambda: ANOMALY)

    response = client.get("/api/ai/analyze")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "available": True,
        "status": "success",
        "prediction": PREDICTION,
        "anomaly": ANOMALY,
        "errors": {},
    }


def test_prediction_failure_preserves_successful_anomaly(client, monkeypatch):
    def fail_prediction():
        raise HTTPException(status_code=503, detail="private model path")

    monkeypatch.setattr(main, "ai_prediction", fail_prediction)
    monkeypatch.setattr(main, "ai_anomaly", lambda: ANOMALY)

    response = client.get("/api/ai/analyze")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "partial"
    assert payload["prediction"] is None
    assert payload["anomaly"] == ANOMALY
    assert payload["errors"]["prediction"]["status_code"] == 503
    assert payload["errors"]["prediction"]["message"] == "Analysis failed."
    assert "private" not in response.text


def test_anomaly_failure_preserves_successful_prediction(client, monkeypatch):
    monkeypatch.setattr(main, "ai_prediction", lambda: PREDICTION)

    def fail_anomaly():
        raise HTTPException(status_code=503, detail="private model path")

    monkeypatch.setattr(main, "ai_anomaly", fail_anomaly)

    response = client.get("/api/ai/analyze")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "partial"
    assert payload["prediction"] == PREDICTION
    assert payload["anomaly"] is None
    assert "anomaly" in payload["errors"]
    assert "private" not in response.text


def test_total_failure_returns_structured_errors_without_details(client, monkeypatch):
    def fail_prediction():
        raise RuntimeError("sensitive model data")

    def fail_anomaly():
        raise HTTPException(status_code=400, detail="private input details")

    monkeypatch.setattr(main, "ai_prediction", fail_prediction)
    monkeypatch.setattr(main, "ai_anomaly", fail_anomaly)

    response = client.get("/api/ai/analyze")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is False
    assert payload["available"] is False
    assert payload["status"] == "error"
    assert payload["prediction"] is None
    assert payload["anomaly"] is None
    assert set(payload["errors"]) == {"prediction", "anomaly"}
    assert "sensitive" not in response.text
    assert "private" not in response.text
