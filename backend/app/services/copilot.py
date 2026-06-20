from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import httpx

from ..models import CopilotRequest
from .precomputed_store import PrecomputedStore


HF_CHAT_URL = "https://router.huggingface.co/v1/chat/completions"
DEFAULT_HF_MODEL = "Qwen/Qwen2.5-7B-Instruct:cheapest"
COMPLIANCE_WARNING = (
    "ParkWatch uses official parking-violation data only. It reports obstruction-risk "
    "and enforcement-priority proxies, not measured congestion or measured delay."
)

_CACHE: dict[str, dict[str, Any]] = {}


async def answer_copilot(request: CopilotRequest, store: PrecomputedStore) -> dict[str, Any]:
    context = build_graph_context_pack(request, store)
    cache_key = _cache_key(request, context)
    if cache_key in _CACHE:
        cached = _CACHE[cache_key].copy()
        cached["cached"] = True
        return cached

    fallback = build_fallback_answer(request, context)
    hf_token = os.getenv("HF_TOKEN")
    model = os.getenv("HF_MODEL", DEFAULT_HF_MODEL)
    if not hf_token:
        result = _response(fallback, "local_fallback", model, context)
        _CACHE[cache_key] = result
        return result

    try:
        answer = await _call_hf(request, context, hf_token, model)
        result = _response(answer, "hf", model, context)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        result = _response(
            fallback,
            "local_fallback",
            model,
            context,
            extra_warning=f"HF unavailable, so ParkWatch used the deterministic fallback ({type(exc).__name__}).",
        )

    _CACHE[cache_key] = result
    return result


def build_graph_context_pack(request: CopilotRequest, store: PrecomputedStore) -> dict[str, Any]:
    filtered = _filtered_hotspots(store, request)
    selected = _selected_hotspot(request, store, filtered)
    selected_graph = store.cell_graph(selected["grid_cell_id"]) if selected else None
    forecast_items = store.forecast.get("items", [])
    top_forecasts = forecast_items[:5]
    top_hotspots = filtered[:5]
    stations = store.stations()[:5]
    moderate = _impact_proxy(filtered, store.hotspots, limit=10, reduction=0.2)

    evidence = [
        {
            "label": "Dataset",
            "value": (
                f"{len(store.hotspots):,} hotspots, {len(store.edges):,} graph edges, "
                f"{sum(item['violation_count'] for item in store.hotspots):,} official violations"
            ),
        },
        {
            "label": "Filtered view",
            "value": f"{len(filtered):,} hotspots match the current dashboard filters.",
        },
        {
            "label": "Compliance",
            "value": "Proxy only; no measured congestion-speed, delay, or percent congestion reduction claim.",
        },
    ]

    if selected:
        evidence.append(
            {
                "label": "Selected hotspot",
                "value": (
                    f"{_hotspot_name(selected)} has {selected['violation_count']:,} violations, "
                    f"risk {selected['obstruction_risk_score']:.1f}, priority "
                    f"{selected['enforcement_priority_score']:.1f}, confidence {selected['confidence']}."
                ),
            }
        )

    if top_forecasts:
        first = top_forecasts[0]
        evidence.append(
            {
                "label": "Forecast leader",
                "value": (
                    f"{first.get('location') or first.get('junction') or first['grid_cell_id']} has "
                    f"predicted priority {first['predicted_enforcement_priority']:.1f} for "
                    f"{store.forecast.get('forecast_week') or 'the forecast week'}."
                ),
            }
        )

    return {
        "active_tab": request.active_tab,
        "mode": request.mode,
        "filters": request.filters.model_dump(),
        "summary": store.summary(),
        "selected": _compact_hotspot(selected) if selected else None,
        "neighbors": [
            _compact_hotspot(item) for item in (selected_graph or {}).get("neighbors", [])[:3]
        ],
        "top_hotspots": [_compact_hotspot(item) for item in top_hotspots],
        "top_forecasts": [_compact_forecast(item) for item in top_forecasts],
        "top_stations": stations,
        "impact_proxy": moderate,
        "evidence": evidence,
        "guardrails": [
            "Use only the supplied ParkWatch context.",
            "Do not claim measured congestion, measured delay, minutes saved, or exact congestion reduction.",
            "Use phrases like modeled obstruction-exposure reduction and enforcement-priority candidate.",
            "If evidence is insufficient, say so directly.",
        ],
    }


async def _call_hf(
    request: CopilotRequest, context: dict[str, Any], hf_token: str, model: str
) -> str:
    timeout = float(os.getenv("HF_TIMEOUT_SECONDS", "8"))
    messages = [
        {
            "role": "system",
            "content": (
                "You are ParkWatch Analyst Copilot. Answer concisely from the supplied "
                "ParkWatch JSON context only. Be useful for a civic-tech hackathon demo. "
                "Never claim measured congestion reduction, measured delay, minutes saved, "
                "or traffic-speed impact. Include 2-4 evidence bullets when possible."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": request.question,
                    "context": _trim_context_for_prompt(context),
                },
                ensure_ascii=True,
            ),
        },
    ]
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            HF_CHAT_URL,
            headers={
                "Authorization": f"Bearer {hf_token}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": 420,
                "temperature": 0.25,
            },
        )

    if response.status_code in {402, 429} or response.status_code >= 500:
        response.raise_for_status()
    if response.status_code >= 400:
        response.raise_for_status()

    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("HF returned an empty response")
    return _sanitize_claims(content.strip())


def build_fallback_answer(request: CopilotRequest, context: dict[str, Any]) -> str:
    selected = context.get("selected")
    top_hotspots = context.get("top_hotspots", [])
    top_forecasts = context.get("top_forecasts", [])
    impact = context.get("impact_proxy", {})
    question = request.question.lower()

    if "limitation" in question or request.mode == "limitations":
        return (
            "ParkWatch is intentionally conservative: it uses official parking-violation "
            "records to estimate obstruction-risk and enforcement-priority proxies. It does "
            "not contain traffic speeds, travel times, or measured delay, so it should not be "
            "presented as measured congestion reduction.\n\n"
            f"Evidence:\n- {context['evidence'][0]['value']}\n"
            f"- {context['evidence'][1]['value']}\n"
            "- The impact tab is a scenario estimate for modeled obstruction exposure."
        )

    if "forecast" in question or request.mode == "forecast":
        leader = top_forecasts[0] if top_forecasts else None
        if not leader:
            return "Forecast evidence is not available in the current data pack."
        return (
            f"The forecast priority leader is {leader['name']} with predicted priority "
            f"{leader['predicted_enforcement_priority']:.1f} and predicted violations "
            f"{leader['predicted_violation_count']:.1f}. Treat this as a planning signal, "
            "not a measured congestion forecast.\n\n"
            f"Evidence:\n- Forecast week: {context['summary'].get('metadata', {}).get('generated_at', 'available in backend metadata')}\n"
            f"- Confidence: {leader['confidence']}\n"
            f"- Reason codes: {', '.join(leader['reason_codes'][:3]) or 'not listed'}"
        )

    if "pitch" in question or request.mode == "judge_pitch":
        return (
            "ParkWatch turns official parking-violation records into an explainable patrol "
            "prioritization dashboard. The demo combines hotspot ranking, spatial graph "
            "neighbors, forecast signals, scenario impact proxies, and a natural-language "
            "analyst layer while keeping the claims honest.\n\n"
            f"Evidence:\n- {context['evidence'][0]['value']}\n"
            f"- Top 10 moderate scenario: {impact.get('filtered_reduction_pct', 0):.1f}% of filtered modeled obstruction exposure.\n"
            "- Outputs are audit-friendly because every answer is grounded in local ParkWatch data."
        )

    if selected:
        neighbors = context.get("neighbors", [])
        neighbor_line = (
            f" It also has {len(neighbors)} nearby graph neighbors in the context pack."
            if neighbors
            else ""
        )
        return (
            f"{selected['name']} is an enforcement-priority candidate with priority "
            f"{selected['enforcement_priority_score']:.1f}, obstruction-risk "
            f"{selected['obstruction_risk_score']:.1f}, {selected['violation_count']:,} "
            f"official violations, and {selected['confidence']} confidence.{neighbor_line}\n\n"
            f"Evidence:\n- Station: {selected.get('station') or 'Unknown'}\n"
            f"- Peak: {selected.get('peak_weekday') or 'Unknown'} "
            f"{selected.get('peak_hour') if selected.get('peak_hour') is not None else ''}:00\n"
            f"- Reason codes: {', '.join(selected['reason_codes'][:3]) or 'not listed'}"
        )

    if top_hotspots:
        leader = top_hotspots[0]
        return (
            f"The current filtered view has {len(top_hotspots)} leading hotspots in the context pack. "
            f"The top candidate is {leader['name']} with priority "
            f"{leader['enforcement_priority_score']:.1f} and risk "
            f"{leader['obstruction_risk_score']:.1f}.\n\n"
            f"Evidence:\n- {context['evidence'][1]['value']}\n"
            f"- Top 10 moderate scenario: {impact.get('filtered_reduction_pct', 0):.1f}% of filtered modeled obstruction exposure.\n"
            "- This is a proxy estimate, not measured congestion reduction."
        )

    return "No matching hotspot context is available for the current dashboard filters."


def _response(
    answer: str,
    provider: str,
    model: str | None,
    context: dict[str, Any],
    extra_warning: str | None = None,
) -> dict[str, Any]:
    warnings = [COMPLIANCE_WARNING]
    if extra_warning:
        warnings.append(extra_warning)
    return {
        "answer": _sanitize_claims(answer),
        "provider": provider,
        "model": model,
        "cached": False,
        "evidence": context["evidence"],
        "warnings": warnings,
    }


def _filtered_hotspots(store: PrecomputedStore, request: CopilotRequest) -> list[dict[str, Any]]:
    filters = request.filters
    filtered = []
    for hotspot in store.hotspots:
        if filters.station and filters.station != "All stations":
            if hotspot.get("dominant_station") != filters.station:
                continue
        if filters.confidence and filters.confidence != "All confidence":
            if hotspot.get("confidence") != filters.confidence:
                continue
        if filters.violation_type and filters.violation_type != "All violations":
            if hotspot.get("dominant_violation_type") != filters.violation_type:
                continue
        if filters.weekday and filters.weekday != "All weekdays":
            if hotspot.get("peak_weekday") != filters.weekday:
                continue
        if filters.hour is not None:
            if hotspot.get("peak_hour") != filters.hour:
                continue
        filtered.append(hotspot)
    return filtered


def _selected_hotspot(
    request: CopilotRequest, store: PrecomputedStore, filtered: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if request.selected_cell_id:
        selected = store.get_hotspot(request.selected_cell_id)
        if selected:
            return selected
    return filtered[0] if filtered else None


def _compact_hotspot(hotspot: dict[str, Any] | None) -> dict[str, Any] | None:
    if hotspot is None:
        return None
    return {
        "cell_id": hotspot["grid_cell_id"],
        "name": _hotspot_name(hotspot),
        "station": hotspot.get("dominant_station"),
        "junction": hotspot.get("dominant_junction"),
        "violation_type": hotspot.get("dominant_violation_type"),
        "violation_count": hotspot["violation_count"],
        "obstruction_risk_score": round(hotspot["obstruction_risk_score"], 1),
        "enforcement_priority_score": round(hotspot["enforcement_priority_score"], 1),
        "confidence": hotspot["confidence"],
        "priority_band": hotspot["priority_band"],
        "peak_weekday": hotspot.get("peak_weekday"),
        "peak_hour": hotspot.get("peak_hour"),
        "neighbor_influence": round(hotspot["neighbor_influence"], 2),
        "reason_codes": hotspot.get("reason_codes", []),
    }


def _compact_forecast(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "cell_id": item["grid_cell_id"],
        "name": item.get("location") or item.get("junction") or item["grid_cell_id"],
        "station": item.get("station"),
        "predicted_violation_count": round(item["predicted_violation_count"], 1),
        "prediction_interval": [
            round(item["prediction_interval_low"], 1),
            round(item["prediction_interval_high"], 1),
        ],
        "predicted_obstruction_risk": round(item["predicted_obstruction_risk"], 1),
        "predicted_enforcement_priority": round(item["predicted_enforcement_priority"], 1),
        "forecast_stability": round(item["forecast_stability"], 1),
        "confidence": item["confidence"],
        "reason_codes": item.get("forecast_reason_codes") or item.get("reason_codes", []),
    }


def _impact_proxy(
    filtered: list[dict[str, Any]],
    all_hotspots: list[dict[str, Any]],
    limit: int,
    reduction: float,
) -> dict[str, Any]:
    filtered_exposure = sum(_obstruction_exposure(item) for item in filtered)
    city_exposure = sum(_obstruction_exposure(item) for item in all_hotspots)
    top_reduced = sum(
        _obstruction_exposure(item) * reduction
        for item in sorted(filtered, key=_obstruction_exposure, reverse=True)[:limit]
    )
    return {
        "scenario": "Moderate targeted enforcement",
        "assumption": "20% fewer repeat observed violations in selected hotspots",
        "top_10_reduced_exposure_units": round(top_reduced),
        "filtered_reduction_pct": round(
            (top_reduced / filtered_exposure) * 100, 1
        )
        if filtered_exposure
        else 0,
        "city_reduction_pct": round((top_reduced / city_exposure) * 100, 1)
        if city_exposure
        else 0,
    }


def _obstruction_exposure(hotspot: dict[str, Any]) -> float:
    confidence = {"High": 1.0, "Medium": 0.75, "Low": 0.45}.get(
        hotspot.get("confidence"), 0.45
    )
    severity = max(float(hotspot.get("mean_severity", 1)), 1)
    peak = 1 + min(float(hotspot.get("temporal_concentration", 0)), 0.5) * 0.4
    recurrence = 1 + min(float(hotspot.get("active_weeks", 0)) / 16, 1) * 0.25
    return float(hotspot["violation_count"]) * severity * peak * recurrence * confidence


def _hotspot_name(hotspot: dict[str, Any]) -> str:
    return (
        hotspot.get("representative_location")
        or hotspot.get("dominant_junction")
        or hotspot["grid_cell_id"]
    )


def _trim_context_for_prompt(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "active_tab": context["active_tab"],
        "filters": context["filters"],
        "selected": context["selected"],
        "neighbors": context["neighbors"],
        "top_hotspots": context["top_hotspots"],
        "top_forecasts": context["top_forecasts"][:3],
        "impact_proxy": context["impact_proxy"],
        "evidence": context["evidence"],
        "guardrails": context["guardrails"],
    }


def _sanitize_claims(answer: str) -> str:
    replacements = {
        "measured congestion reduction": "modeled obstruction-exposure reduction",
        "congestion reduction": "obstruction-risk proxy reduction",
        "reduces congestion": "may reduce obstruction exposure",
        "traffic delay": "traffic-delay proxy",
        "minutes saved": "modeled exposure units reduced",
    }
    sanitized = answer
    for forbidden, replacement in replacements.items():
        sanitized = sanitized.replace(forbidden, replacement)
        sanitized = sanitized.replace(forbidden.title(), replacement)
    return sanitized


def _cache_key(request: CopilotRequest, context: dict[str, Any]) -> str:
    payload = {
        "question": request.question,
        "mode": request.mode,
        "active_tab": request.active_tab,
        "selected": (context.get("selected") or {}).get("cell_id"),
        "filters": context.get("filters"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
