from typing import Optional

SEVERITY_WEIGHTS = {
    "mild":     1,
    "moderate": 2,
    "severe":   3,
}


def _score_symptoms(symptoms: dict) -> int:
    """
    Accepts the list-based symptom structure.
    Future AI replacement point: swap this function's internals only.
    """
    all_symptoms = symptoms.get("symptoms", []) + symptoms.get("other_symptoms", [])
    if not all_symptoms:
        return 0
    total = sum(SEVERITY_WEIGHTS.get(s.get("severity", "mild"), 1) for s in all_symptoms)
    return min(9, total)


def assess_environment_risk(
    temperature: float,
    humidity: float,
    aqi: int | None,
    symptoms: Optional[dict] = None,
) -> dict:

    score = 100
    recommendations = []
    alerts = []

    # ------------------------------------------------------------------
    # Stage 1: Heat Stress
    # ------------------------------------------------------------------
    if temperature > 32 and humidity > 70:
        heat_risk = "High"
        score -= 40
        alerts.append("High Heat Stress")
        recommendations.append(
            "Hydrate immediately and avoid outdoor physical activity."
        )
    elif temperature > 29 and humidity > 60:
        heat_risk = "Moderate"
        score -= 15
        recommendations.append(
            "Drink water regularly and take breaks in cool areas."
        )
    else:
        heat_risk = "Low"

    # ------------------------------------------------------------------
    # Stage 2: Respiratory / AQI
    # ------------------------------------------------------------------
    if aqi is None:
        respiratory_risk = "Unknown"
        recommendations.append(
            "Air quality data is currently unavailable. Take precautions if outdoors."
        )
    elif aqi > 200:
        respiratory_risk = "Critical"
        score -= 45
        alerts.append("Critical Air Quality")
        recommendations.append(
            "Air quality is hazardous. Stay indoors, keep windows closed, and use an air purifier."
        )
    elif aqi > 150:
        respiratory_risk = "High"
        score -= 35
        alerts.append("Poor Air Quality")
        recommendations.append(
            "Unhealthy air quality. Avoid all outdoor activity, especially for asthma patients."
        )
    elif aqi > 100:
        respiratory_risk = "Moderate"
        score -= 20
        recommendations.append(
            "Air quality is unhealthy for sensitive groups. Asthma patients should limit outdoor exposure."
        )
    elif aqi > 50:
        respiratory_risk = "Low-Moderate"
        score -= 10
        recommendations.append(
            "Moderate air quality. Sensitive individuals should monitor symptoms."
        )
    else:
        respiratory_risk = "Low"

    # Humidity interaction — high humidity makes particulate matter worse
    # Only applies when air quality is already a concern
    if humidity > 75 and aqi is not None and aqi > 100:
        score -= 5
        recommendations.append(
            "High humidity is amplifying air quality risk. Ensure good indoor ventilation."
        )

    # ------------------------------------------------------------------
    # Stage 3: Symptom Scoring
    # ------------------------------------------------------------------
    asthma_attack_risk = "Low"

    if symptoms:
        symptom_score = _score_symptoms(symptoms)
        score -= symptom_score * 3

        env_is_elevated = (
            heat_risk in ("Moderate", "High") or
            respiratory_risk in ("Moderate", "High", "Critical", "Low-Moderate")
        )

        if symptom_score >= 6 and env_is_elevated:
            asthma_attack_risk = "High"
            alerts.append("Elevated Asthma Attack Risk")
            recommendations.append(
                "Your reported symptoms combined with current conditions are concerning. "
                "Use your reliever inhaler if prescribed and move indoors."
            )
        elif symptom_score >= 3:
            asthma_attack_risk = "Moderate"
            recommendations.append(
                "Noticeable symptoms reported. Reduce physical exertion and monitor closely."
            )
        elif symptom_score > 0:
            recommendations.append(
                "Mild symptoms noted. Continue monitoring how you feel."
            )

    # ------------------------------------------------------------------
    # Stage 4: Aggregation
    # ------------------------------------------------------------------
    final_score = max(0, score)

    if final_score >= 85:
        overall_status = "Safe"
    elif final_score >= 60:
        overall_status = "Caution"
    elif final_score >= 35:
        overall_status = "Unsafe"
    else:
        overall_status = "Dangerous"

    if not recommendations:
        recommendations = ["Conditions are optimal. Safe for all activities."]

    return {
        "health_score":       final_score,
        "overall_status":     overall_status,
        "heat_stress_risk":   heat_risk,
        "respiratory_risk":   respiratory_risk,
        "asthma_attack_risk": asthma_attack_risk,
        "active_alerts":      alerts,
        "recommendations":    recommendations,
    }