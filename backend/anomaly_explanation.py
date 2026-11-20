import math


ANOMALY_METRICS = (
    ("download_mbps", "Download speed", "Mbps"),
    ("upload_mbps", "Upload speed", "Mbps"),
    ("ping_ms", "Ping", "ms"),
    ("jitter_ms", "Jitter", "ms"),
    ("packet_loss", "Packet loss", "%"),
)


def build_anomaly_explanation(
    features,
    values,
    normalized_values,
    reconstructed_values,
    scaler,
):
    """Build per-network-metric diagnostics from the model's reconstruction."""
    diagnostics = []

    for feature, name, unit in ANOMALY_METRICS:
        if feature not in features:
            continue

        index = features.index(feature)

        if (
            index >= len(values)
            or index >= len(normalized_values)
            or index >= len(reconstructed_values)
            or index >= len(scaler["mean"])
            or index >= len(scaler["std"])
        ):
            continue

        try:
            observed = float(values[index])
            normalized = float(normalized_values[index])
            reconstructed = float(reconstructed_values[index])
            mean = float(scaler["mean"][index])
            scale = float(scaler["std"][index])
        except (TypeError, ValueError):
            continue

        if not all(
            math.isfinite(value)
            for value in (observed, normalized, reconstructed, mean, scale)
        ):
            continue

        if abs(scale) < 1e-8:
            scale = 1.0

        reconstructed_value = reconstructed * scale + mean
        normalized_error = abs(reconstructed - normalized)
        absolute_error = abs(reconstructed_value - observed)

        if not all(
            math.isfinite(value)
            for value in (
                reconstructed_value,
                normalized_error,
                absolute_error,
            )
        ):
            continue

        diagnostics.append(
            {
                "feature": feature,
                "name": name,
                "unit": unit,
                "observed_value": observed,
                "reconstructed_value": reconstructed_value,
                "absolute_error": absolute_error,
                "normalized_error": normalized_error,
                "_feature_index": index,
            }
        )

    largest_error = max(
        (item["normalized_error"] for item in diagnostics),
        default=0.0,
    )
    scaled_squared_errors = [
        (item["normalized_error"] / largest_error) ** 2
        if largest_error > 0
        else 0.0
        for item in diagnostics
    ]
    total_scaled_error = sum(scaled_squared_errors)

    for index, item in enumerate(diagnostics):
        item["contribution_percent"] = (
            scaled_squared_errors[index] / total_scaled_error * 100
            if total_scaled_error > 0
            else 0.0
        )

    diagnostics.sort(
        key=lambda item: (
            -item["contribution_percent"],
            item["_feature_index"],
        )
    )

    for rank, item in enumerate(diagnostics, start=1):
        item["rank"] = rank
        del item["_feature_index"]

    return {
        "normalization": "share_of_five_metric_squared_errors",
        "metrics": diagnostics,
    }
