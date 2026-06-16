import type { HeatmapPoint, TemporalHour, TemporalWeekday } from "../lib/types";

type TemporalHeatmapProps = {
  hourly: TemporalHour[];
  weekday: TemporalWeekday[];
  heatmap: HeatmapPoint[];
};

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function TemporalHeatmap({ hourly, weekday, heatmap }: TemporalHeatmapProps) {
  const maxHeatmap = Math.max(...heatmap.map((item) => item.violation_count), 1);
  const maxHourly = Math.max(...hourly.map((item) => item.violation_count), 1);
  const weekdayTotals = new Map(weekday.map((item) => [item.weekday, item.violation_count]));
  const heatmapLookup = new Map(
    heatmap.map((item) => [`${item.weekday}-${item.hour}`, item.violation_count])
  );

  return (
    <section className="panel temporal-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Temporal patterns</p>
          <h2>When should enforcement happen?</h2>
        </div>
      </div>

      <div className="hour-bars" aria-label="Hourly violations">
        {hourly.map((item) => (
          <span
            key={item.hour}
            style={{ height: `${8 + (item.violation_count / maxHourly) * 72}px` }}
            title={`${item.hour}:00 - ${item.violation_count.toLocaleString("en-IN")} violations`}
          />
        ))}
      </div>

      <div className="heatmap-grid" aria-label="Weekday by hour heatmap">
        {WEEKDAYS.map((day) => (
          <div className="heatmap-row" key={day}>
            <span>{day.slice(0, 3)}</span>
            {Array.from({ length: 24 }, (_, hour) => {
              const count = heatmapLookup.get(`${day}-${hour}`) ?? 0;
              const opacity = 0.16 + (count / maxHeatmap) * 0.84;
              return (
                <i
                  key={hour}
                  style={{ opacity }}
                  title={`${day} ${hour}:00 - ${count.toLocaleString("en-IN")} violations`}
                />
              );
            })}
            <strong>{(weekdayTotals.get(day) ?? 0).toLocaleString("en-IN")}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}
