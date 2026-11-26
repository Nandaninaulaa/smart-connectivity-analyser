const test = require("node:test");
const assert = require("node:assert/strict");

const {
    normalizeForecastResponse,
    resolveForecastRiskMeta,
    formatForecastRange
} = require("../js/script.js");

test("normalizeForecastResponse rejects empty or invalid payloads", () => {
    assert.equal(normalizeForecastResponse(null), null);
    assert.equal(normalizeForecastResponse({}), null);
    assert.equal(normalizeForecastResponse({ horizons: [] }), null);
    assert.equal(normalizeForecastResponse({ horizons: [{ horizon: "1h" }] }), null);
});

test("normalizeForecastResponse accepts valid multi-horizon forecast payload", () => {
    const payload = {
        success: true,
        generated_at: "2026-11-26T18:00:00+00:00",
        history_summary: { total_records: 8, fallback_used: false },
        degradation_risk: { level: "Moderate", score: 42.5, reasons: ["Latency rising"] },
        horizons: [
            {
                horizon: "1h",
                hours_ahead: 1,
                degradation_risk: { level: "Low", score: 20 },
                metrics: {
                    connectivity_score: { predicted: 78.4, lower: 71.0, upper: 85.8, unit: "/100" }
                }
            }
        ]
    };

    const normalized = normalizeForecastResponse(payload);
    assert.ok(normalized);
    assert.equal(normalized.horizons.length, 1);
    assert.equal(normalized.degradation_risk.level, "Moderate");
});

test("resolveForecastRiskMeta maps risk levels to accessible labels and icons", () => {
    assert.deepEqual(resolveForecastRiskMeta("Low"), {
        key: "low",
        label: "Low Risk",
        iconClass: "fa-solid fa-circle-check"
    });
    assert.deepEqual(resolveForecastRiskMeta("Moderate"), {
        key: "moderate",
        label: "Moderate Risk",
        iconClass: "fa-solid fa-circle-exclamation"
    });
    assert.deepEqual(resolveForecastRiskMeta("High"), {
        key: "high",
        label: "High Risk",
        iconClass: "fa-solid fa-triangle-exclamation"
    });
    assert.equal(resolveForecastRiskMeta("unknown").key, "unavailable");
});

test("formatForecastRange formats point forecast and confidence bounds safely", () => {
    assert.equal(
        formatForecastRange({ predicted: 79.4, lower: 73.2, upper: 85.6, unit: "/100" }, 1),
        "79.4 /100 (73.2 – 85.6)"
    );
    assert.equal(
        formatForecastRange({ predicted: null, lower: null, upper: null, unit: "/100" }, 1),
        "Unavailable"
    );
    assert.equal(formatForecastRange(null, 1), "Unavailable");
});
