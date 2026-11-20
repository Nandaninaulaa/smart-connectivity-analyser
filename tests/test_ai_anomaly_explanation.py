import math
from contextlib import nullcontext

import pytest

from backend.anomaly_explanation import build_anomaly_explanation
from backend import main


FEATURES = [
    "download_mbps",
    "upload_mbps",
    "ping_ms",
    "jitter_ms",
    "packet_loss",
    "connectivity_score",
]
SCALER = {
    "features": FEATURES,
    "mean": [50, 10, 20, 3, 0, 80],
    "std": [10, 5, 10, 2, 1, 10],
}
VALUES = [50, 10, 20, 3, 0, 80]
NORMALIZED = [0, 0, 0, 0, 0, 0]


class FakeTensor:
    def __init__(self, values, shape=None):
        while isinstance(values, (list, tuple)) and values and isinstance(
            values[0], (list, tuple)
        ):
            values = [value for row in values for value in row]
        self.values = list(values) if isinstance(values, (list, tuple)) else [values]
        self.shape = shape

    def reshape(self, *shape):
        self.shape = shape
        return self

    def __getitem__(self, key):
        return FakeTensor(self.values, (1, len(self.values)))

    def __sub__(self, other):
        return FakeTensor(
            [left - right for left, right in zip(self.values, other.values)],
            self.shape,
        )

    def __pow__(self, power):
        return FakeTensor([value**power for value in self.values], self.shape)

    def tolist(self):
        return self.values

    def item(self):
        assert len(self.values) == 1
        return self.values[0]


class FakeTorch:
    float32 = "float32"

    @staticmethod
    def tensor(values, dtype=None):
        return FakeTensor(values)

    @staticmethod
    def no_grad():
        return nullcontext()

    @staticmethod
    def mean(tensor):
        return FakeTensor([sum(tensor.values) / len(tensor.values)])


def test_normal_reconstruction_has_zero_metric_contributions():
    explanation = build_anomaly_explanation(
        FEATURES,
        VALUES,
        NORMALIZED,
        NORMALIZED,
        SCALER,
    )

    assert [metric["feature"] for metric in explanation["metrics"]] == [
        "download_mbps",
        "upload_mbps",
        "ping_ms",
        "jitter_ms",
        "packet_loss",
    ]
    assert all(metric["normalized_error"] == 0 for metric in explanation["metrics"])
    assert all(metric["contribution_percent"] == 0 for metric in explanation["metrics"])


def test_anomalous_reconstruction_ranks_standardized_squared_errors():
    explanation = build_anomaly_explanation(
        FEATURES,
        VALUES,
        NORMALIZED,
        [1, 2, 3, 4, 5, 100],
        SCALER,
    )
    metrics = explanation["metrics"]

    assert [metric["feature"] for metric in metrics] == [
        "packet_loss",
        "jitter_ms",
        "ping_ms",
        "upload_mbps",
        "download_mbps",
    ]
    assert [metric["rank"] for metric in metrics] == [1, 2, 3, 4, 5]
    assert sum(metric["contribution_percent"] for metric in metrics) == pytest.approx(
        100
    )
    assert metrics[0]["contribution_percent"] == pytest.approx(25 / 55 * 100)
    assert metrics[0]["reconstructed_value"] == pytest.approx(5)


@pytest.mark.parametrize(
    "values,normalized,reconstructed",
    [
        ([50, None, 20, 3, 0, 80], NORMALIZED, NORMALIZED),
        ([50, 10, 20, 3, float("nan"), 80], NORMALIZED, NORMALIZED),
        ([50, 10, 20, 3, 0, 80], NORMALIZED, [0, float("inf"), 0, 0, 0, 0]),
        ([50, None], [0, 0], [0, 0]),
    ],
)
def test_missing_incomplete_and_non_finite_values_are_omitted(
    values,
    normalized,
    reconstructed,
):
    explanation = build_anomaly_explanation(
        FEATURES,
        values,
        normalized,
        reconstructed,
        SCALER,
    )

    assert all(
        math.isfinite(metric[field])
        for metric in explanation["metrics"]
        for field in (
            "observed_value",
            "reconstructed_value",
            "absolute_error",
            "normalized_error",
            "contribution_percent",
        )
    )
    if len(values) == 2:
        assert [metric["feature"] for metric in explanation["metrics"]] == [
            "download_mbps"
        ]


def test_zero_variance_scaler_and_zero_error_normalize_safely():
    zero_variance_scaler = {
        "features": FEATURES,
        "mean": [4] * len(FEATURES),
        "std": [0] * len(FEATURES),
    }

    explanation = build_anomaly_explanation(
        FEATURES,
        [4] * len(FEATURES),
        [0] * len(FEATURES),
        [0] * len(FEATURES),
        zero_variance_scaler,
    )
    assert all(metric["contribution_percent"] == 0 for metric in explanation["metrics"])


@pytest.mark.parametrize(
    "reconstruction,threshold,expected_anomaly",
    [
        ([0, 0, 0, 0, 0, 0], 0.05, False),
        ([0, 0, 0, 0, 1, 0], 0.05, True),
    ],
)
def test_anomaly_api_preserves_existing_fields_and_adds_explanation(
    client,
    monkeypatch,
    reconstruction,
    threshold,
    expected_anomaly,
):
    class ControlledModel:
        def __call__(self, sample):
            assert sample.shape == (1, 1, len(FEATURES))
            return FakeTensor([reconstruction], (1, len(FEATURES)))

    monkeypatch.setattr(main, "torch", FakeTorch())
    monkeypatch.setattr(main, "FEATURES", FEATURES)
    monkeypatch.setattr(
        main,
        "normalize_values",
        lambda values, scaler: [
            (value - scaler["mean"][index]) / scaler["std"][index]
            for index, value in enumerate(values)
        ],
    )
    monkeypatch.setattr(main, "AI_MODELS_READY", True)
    monkeypatch.setattr(main, "ai_anomaly_model", ControlledModel())
    monkeypatch.setattr(main, "ai_scaler", SCALER)
    monkeypatch.setattr(main, "ai_anomaly_threshold", threshold)
    monkeypatch.setattr(
        main,
        "load_network_data",
        lambda: [{"timestamp": "2026-01-01T00:00:00Z", "values": VALUES}],
    )

    response = client.get("/api/ai/anomaly")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["model"] == "Transformer Autoencoder"
    assert body["timestamp"] == "2026-01-01T00:00:00Z"
    assert body["anomaly"] is expected_anomaly
    assert body["threshold"] == threshold
    assert body["status"] in ("Anomaly detected", "No anomaly detected")
    expected_error = sum(
        (actual - expected) ** 2
        for actual, expected in zip(reconstruction, NORMALIZED)
    ) / len(FEATURES)
    assert body["reconstruction_error"] == pytest.approx(
        round(expected_error, 6)
    )
    assert body["explanation"]["normalization"] == (
        "share_of_five_metric_squared_errors"
    )
    assert len(body["explanation"]["metrics"]) == 5
