import type { ForecastItem, Hotspot } from "./types";

type LabelSource = Pick<
  Hotspot,
  "grid_cell_id" | "representative_location" | "dominant_junction" | "dominant_station"
>;

type ForecastLabelSource = Pick<
  ForecastItem,
  "grid_cell_id" | "location" | "junction" | "station"
>;

export function hotspotName(hotspot: LabelSource) {
  return (
    firstLocationKeyword(hotspot.representative_location) ??
    cleanJunctionName(hotspot.dominant_junction) ??
    hotspot.dominant_station ??
    hotspot.grid_cell_id
  );
}

export function hotspotContext(hotspot: LabelSource) {
  const station = hotspot.dominant_station ?? "Unknown station";
  return `${station} - Cell ${hotspot.grid_cell_id}`;
}

export function forecastHotspotName(item: ForecastLabelSource) {
  return (
    firstLocationKeyword(item.location) ??
    cleanJunctionName(item.junction) ??
    item.station ??
    item.grid_cell_id
  );
}

export function forecastHotspotContext(item: ForecastLabelSource) {
  const station = item.station ?? "Unknown station";
  return `${station} - Cell ${item.grid_cell_id}`;
}

function firstLocationKeyword(location: string | null) {
  if (!location) return null;
  const [firstSegment] = location.split(",");
  const cleaned = firstSegment?.trim();
  return cleaned || null;
}

function cleanJunctionName(junction: string | null) {
  if (!junction || junction.toLowerCase() === "no junction") return null;
  return junction.replace(/^BTP\d+\s*-\s*/i, "").trim() || junction;
}
