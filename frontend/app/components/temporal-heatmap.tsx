 "use client";

import { useMemo, useState } from "react";
import type { HeatmapPoint, TemporalHour, TemporalWeekday } from "../lib/types";

type TemporalHeatmapProps = {
  hourly: TemporalHour[];
  weekday: TemporalWeekday[];
  heatmap: HeatmapPoint[];
};

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function TemporalHeatmap({ hourly, weekday, heatmap }: TemporalHeatmapProps) {
  const [selectedSlot, setSelectedSlot] = useState<HeatmapPoint | null>(null);
  const maxHeatmap = Math.max(...heatmap.map((item) => item.violation_count), 1);
  const maxHourly = Math.max(...hourly.map((item) => item.violation_count), 1);
  const weekdayTotals = new Map(weekday.map((item) => [item.weekday, item.violation_count]));
  const heatmapLookup = new Map(
    heatmap.map((item) => [`${item.weekday}-${item.hour}`, item.violation_count])
  );
  const peakSlot = useMemo(
    () =>
      heatmap.reduce<HeatmapPoint | null>(
        (peak, item) => (!peak || item.violation_count > peak.violation_count ? item : peak),
        null
      ),
    [heatmap]
  );
  const selected = selectedSlot ?? peakSlot;

  return (
    <section className="panel temporal-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Temporal patterns</p>
          <h2>When should enforcement happen?</h2>
          {selected && (
            <span className="cell-meta">
              Focus: {selected.weekday} {selected.hour.toString().padStart(2, "0")}:00,
              {" "}
              {selected.violation_count.toLocaleString("en-IN")} violations
            </span>
          )}
        </div>
      </div>

      <div className="hour-bars" aria-label="Hourly violations">
        {hourly.map((item) => (
          <span
            key={item.hour}
            className={selected?.hour === item.hour ? "selected" : ""}
            style={{ height: `${8 + (item.violation_count / maxHourly) * 72}px` }}
            title={`${item.hour}:00 - ${item.violation_count.toLocaleString("en-IN")} violations`}
          />
        ))}
      </div>
      <div className="axis-legend" aria-hidden="true">
        <span>00:00</span>
        <span>06:00</span>
        <span>12:00</span>
        <span>18:00</span>
        <span>23:00</span>
      </div>

      <div className="heatmap-grid" aria-label="Weekday by hour heatmap">
        {WEEKDAYS.map((day) => (
          <div className="heatmap-row" key={day}>
            <span>{day.slice(0, 3)}</span>
            {Array.from({ length: 24 }, (_, hour) => {
              const count = heatmapLookup.get(`${day}-${hour}`) ?? 0;
              const isSelected = selected?.weekday === day && selected.hour === hour;
              const isPeak = peakSlot?.weekday === day && peakSlot.hour === hour;
              const opacity = 0.18 + (count / maxHeatmap) * 0.82;
              return (
                <button
                  key={hour}
                  className={`${isSelected ? "selected" : ""} ${isPeak ? "peak" : ""}`}
                  style={{ opacity }}
                  title={`${day} ${hour}:00 - ${count.toLocaleString("en-IN")} violations`}
                  type="button"
                  onClick={() => setSelectedSlot({ weekday: day, hour, violation_count: count })}
                  aria-label={`${day} ${hour}:00 has ${count} violations`}
                />
              );
            })}
            <strong>{(weekdayTotals.get(day) ?? 0).toLocaleString("en-IN")}</strong>
          </div>
        ))}
      </div>
      <div className="heatmap-legend" aria-label="Heatmap legend">
        <span>Lower violations</span>
        <i />
        <span>Higher violations</span>
        {peakSlot && <strong>Peak: {peakSlot.weekday.slice(0, 3)} {peakSlot.hour}:00</strong>}
      </div>
    </section>
  );
}
