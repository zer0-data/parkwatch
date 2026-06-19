import type { Hotspot } from "./types";

export type EnforcementScenario = {
  key: "conservative" | "moderate" | "strong";
  label: string;
  repeatViolationReduction: number;
  description: string;
};

export type ImpactEstimate = {
  hotspot: Hotspot;
  exposure: number;
  reducedExposure: number;
  hotspotExposureReductionPct: number;
  filteredExposureReductionPct: number;
  cityExposureReductionPct: number;
};

export const ENFORCEMENT_SCENARIOS: EnforcementScenario[] = [
  {
    key: "conservative",
    label: "Conservative",
    repeatViolationReduction: 0.1,
    description: "Assumes targeted enforcement reduces repeat observed violations by 10%."
  },
  {
    key: "moderate",
    label: "Moderate",
    repeatViolationReduction: 0.2,
    description: "Assumes targeted enforcement reduces repeat observed violations by 20%."
  },
  {
    key: "strong",
    label: "Strong",
    repeatViolationReduction: 0.3,
    description: "Assumes targeted enforcement reduces repeat observed violations by 30%."
  }
];

export function obstructionExposure(hotspot: Hotspot) {
  const severityWeight = Math.max(hotspot.mean_severity, 1);
  const peakWindowMultiplier = 1 + Math.min(hotspot.temporal_concentration, 0.5) * 0.4;
  const recurrenceMultiplier = 1 + Math.min(hotspot.active_weeks / 16, 1) * 0.25;
  const confidenceMultiplier = {
    High: 1,
    Medium: 0.75,
    Low: 0.45
  }[hotspot.confidence];

  return (
    hotspot.violation_count *
    severityWeight *
    peakWindowMultiplier *
    recurrenceMultiplier *
    confidenceMultiplier
  );
}

export function buildImpactEstimates(
  filteredHotspots: Hotspot[],
  allHotspots: Hotspot[],
  scenario: EnforcementScenario,
  limit = 25
) {
  const filteredExposure = filteredHotspots.reduce(
    (sum, hotspot) => sum + obstructionExposure(hotspot),
    0
  );
  const cityExposure = allHotspots.reduce(
    (sum, hotspot) => sum + obstructionExposure(hotspot),
    0
  );

  return filteredHotspots
    .map((hotspot) => {
      const exposure = obstructionExposure(hotspot);
      const reducedExposure = exposure * scenario.repeatViolationReduction;
      return {
        hotspot,
        exposure,
        reducedExposure,
        hotspotExposureReductionPct: scenario.repeatViolationReduction * 100,
        filteredExposureReductionPct:
          filteredExposure > 0 ? (reducedExposure / filteredExposure) * 100 : 0,
        cityExposureReductionPct: cityExposure > 0 ? (reducedExposure / cityExposure) * 100 : 0
      };
    })
    .sort((a, b) => b.reducedExposure - a.reducedExposure)
    .slice(0, limit);
}

export function totalExposure(hotspots: Hotspot[]) {
  return hotspots.reduce((sum, hotspot) => sum + obstructionExposure(hotspot), 0);
}

export function formatPct(value: number) {
  if (value < 0.1 && value > 0) {
    return "<0.1%";
  }
  return `${value.toFixed(1)}%`;
}
