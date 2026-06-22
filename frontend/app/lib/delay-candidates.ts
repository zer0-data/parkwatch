import type { ForecastResponse, Hotspot } from "./types";
import { forecastHotspotName, hotspotContext, hotspotName } from "./hotspot-labels";

export function buildDelayCandidates(hotspots: Hotspot[], forecast: ForecastResponse, limit = 12) {
  const hotspotById = new Map(hotspots.map((hotspot) => [hotspot.grid_cell_id, hotspot]));
  const forecastCandidates = forecast.items
    .map((item) => {
      const hotspot = hotspotById.get(item.grid_cell_id);
      if (!hotspot) return null;
      return {
        grid_cell_id: item.grid_cell_id,
        latitude: item.latitude,
        longitude: item.longitude,
        location: forecastHotspotName(item),
        context: hotspotContext(hotspot),
        station: item.station ?? hotspot.dominant_station ?? "Unknown",
        predictedViolations: item.predicted_violation_count,
        forecastPriority: item.predicted_enforcement_priority ?? item.predicted_obstruction_risk,
        obstructionRisk: item.predicted_obstruction_risk,
        peakWindow: formatPeakWindow(hotspot)
      };
    })
    .filter((item): item is NonNullable<typeof item> => Boolean(item));

  const candidates =
    forecastCandidates.length > 0
      ? forecastCandidates
      : hotspots.map((hotspot) => ({
          grid_cell_id: hotspot.grid_cell_id,
          latitude: hotspot.latitude,
          longitude: hotspot.longitude,
          location: hotspotName(hotspot),
          context: hotspotContext(hotspot),
          station: hotspot.dominant_station ?? "Unknown",
          predictedViolations: hotspot.violation_count,
          forecastPriority: hotspot.enforcement_priority_score,
          obstructionRisk: hotspot.obstruction_risk_score,
          peakWindow: formatPeakWindow(hotspot)
        }));

  return candidates
    .sort(
      (a, b) =>
        b.forecastPriority - a.forecastPriority ||
        b.predictedViolations - a.predictedViolations ||
        b.obstructionRisk - a.obstructionRisk
    )
    .slice(0, limit);
}

function formatPeakWindow(hotspot: Hotspot) {
  const weekday = hotspot.peak_weekday ?? "Unknown";
  const hour =
    hotspot.peak_hour === null || hotspot.peak_hour === undefined
      ? "unknown hour"
      : `${hotspot.peak_hour.toString().padStart(2, "0")}:00`;
  return `${weekday}, ${hour}`;
}
