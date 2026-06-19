# ParkWatch Methodology and Compliance

## System overview

ParkWatch is an official-data-only analytics prototype. The offline preprocessing
pipeline reads the local official parking violation CSV, creates hotspot and graph
features, computes an Obstruction Risk Score, computes an Enforcement Priority
Score, creates a forecast of future observed violations, and writes JSON outputs.
The FastAPI backend serves only those precomputed JSON files. The Next.js
frontend renders dashboard, explainer, temporal, graph, forecast, and methodology
views.

## Dataset fields used

- `latitude`
- `longitude`
- `location`
- `violation_type`
- `created_datetime`
- `device_id`
- `police_station`
- `junction_name`
- `validation_status`

## Why external data is not used

The current project constraint is official dataset only. ParkWatch does not use
OSM, weather, traffic speed, map tiles, road-network data, or external datasets
in code, preprocessing, scoring, forecasting, or API responses. This keeps the
prototype auditable and avoids unsupported claims about measured congestion.

## Grid graph

Each violation coordinate is assigned to a 0.001-degree grid cell. Each grid cell
is a graph node. Edges are built only from dataset coordinates using haversine
distance between representative cell coordinates. Cells are connected when they
fall within the configured 300 to 500 meter distance band. Neighbor influence is
derived from adjacent grid-cell violation volume and edge weights.

## Representation explainer

ParkWatch represents official observations as decision-support views:

- Hotspot: a 0.001-degree grid cell aggregating observed parking violations.
- Location label: a readable location, junction, or station label, with the grid
  cell retained for traceability.
- Obstruction Risk Score: an interpretable obstruction-risk proxy.
- Enforcement Priority Score: an action-oriented ranking for targeted patrol
  planning.
- Confidence: evidence density from repeated records, not proof of congestion
  impact.
- Temporal heatmap: observed violation frequency by weekday and hour.
- Graph neighborhood: coordinate-derived nearby grid cells, not a road network.
- Forecast: future observed parking violation forecast, not traffic congestion
  prediction.

Supported wording: ParkWatch may say a zone has repeated observed violations,
high obstruction-risk proxy, or high enforcement priority. Unsupported wording:
ParkWatch must not say the current CSV proves measured congestion, measured delay,
minutes saved, or percentage congestion reduction.

## Obstruction Risk Score formula

The Obstruction Risk Score is scaled from 0 to 100 and remains the interpretable
risk proxy:

```text
0.30 * violation volume
+ 0.15 * active-day recurrence
+ 0.10 * device-day support
+ 0.20 * mean severity
+ 0.10 * junction share
+ 0.10 * graph-neighbor influence
+ 0.05 * validation share
```

Severity is derived from official violation types only. High severity includes
double parking, parking in a main road, parking near road crossing, parking near
bus stop/school/hospital etc., parking near traffic light or zebra cross, and
parking opposite another parked vehicle. Parking on footpath is Medium. All other
types are Low.

## Enforcement Priority Score formula

The improved operational model adds a second score for action planning. It uses
only official-CSV-derived features and does not claim measured congestion:

```text
0.28 * Obstruction Risk Score
+ 0.18 * station-normalized violation volume
+ 0.14 * recent 4-week activity
+ 0.12 * peak-hour temporal concentration
+ 0.10 * recent trend ratio
+ 0.08 * graph-neighbor influence
+ 0.06 * confidence evidence level
+ 0.04 * stability across weeks, days, and devices
```

This split keeps the risk score easy to audit while making the operational
ranking better aligned with enforcement decisions. A hotspot can be high risk
but not the first deployment choice if it is less recent, less stable, or less
important within its police-station context.

Priority bands are derived from the Enforcement Priority Score and confidence:

- Deploy first: score at least 60 and not Low confidence.
- Schedule patrol: score at least 40.
- Monitor: all other hotspots.

## Confidence labels

Confidence is evidence density, not proof of traffic impact:

- High: at least 25 violations, 5 active days, and 5 device-days.
- Medium: at least 8 violations and 2 active days.
- Low: all other grid cells.

## Forecast v2

The forecast predicts future observed parking violation counts, not measured
congestion. Forecast v2 uses last 1-week count, last 2-week average, last
4-week average, recent trend ratio, station-normalized recent activity,
graph-neighbor recent activity, temporal concentration, and stability features.
It outputs a predicted count, prediction interval, predicted enforcement priority,
forecast stability, and forecast reason codes.

Validation uses rolling-origin weekly backtesting across recent weekly buckets.
The holdout metrics remain forecast-error measures for observed parking violation
counts, not measured congestion.

## Dashboard EDA Extensions

The dashboard can expand EDA without leaving the official CSV boundary by using
the already-derived hotspot, temporal, station, violation-type, validation, and
graph-neighbor features.

- Enforcement priority zones: hotspots are ranked as deploy-first, scheduled
  patrol, or monitor zones using the Enforcement Priority Score, confidence,
  peak window, recent activity, trend, station-normalized volume, and repeated
  evidence.
- Operational filters: users can narrow the hotspot list by police station,
  confidence, dominant violation type, peak weekday, and peak hour.
- Exportable action list: the filtered enforcement-priority table can be exported
  as CSV for patrol planning and review.
- Scenario impact proxy: the dashboard can model obstruction-exposure reduction
  under conservative, moderate, and strong enforcement assumptions. This uses
  official-CSV-derived exposure units combining violation volume, severity,
  peak concentration, recurrence, and confidence. It is not measured congestion
  reduction.
- Compiled report: the dashboard can generate a deterministic local report from
  loaded hotspot, forecast, station, and scenario-proxy data without an external
  model API.
- Score explanation on demand: clicking the score opens the formula contribution
  breakdown for the selected hotspot. This keeps methodology accessible without
  repeating long method text throughout the dashboard.
- Representation explainer: the app explains what each view represents and what
  claims can and cannot be made from the official CSV.

## Model Improvement Within Current Data

The current model can be improved, but only as a better observed-violation and
obstruction-risk model. It still cannot become a measured congestion model unless
traffic speed, flow, delay, queue, or road-network data are added.

Implemented official-CSV-only upgrades include station-normalized volume, recent
activity, recent trend, temporal concentration, priority bands, stability
features, prediction intervals, predicted enforcement priority, forecast
stability, and rolling-origin forecast validation.

Further reasonable official-CSV-only upgrades include:

- Station-aware baselines: fit recent-activity weights separately by police
  station or station cluster to reduce patrol-pattern bias.
- Feature ablation: compare count-only, temporal-only, spatial-only, and combined
  models to show which signals actually improve forecast error.
- Calibrated priority classes: tune deploy-first, schedule, and monitor thresholds
  against holdout observed violations instead of fixed score bands.
- More granular temporal features: include month, weekday, hour, and interaction
  effects where enough observations exist.
- Scenario calibration: estimate how alternative enforcement assumptions change
  obstruction-exposure proxy units, while clearly avoiding measured congestion
  or measured delay claims.

These upgrades can make hotspot prioritization and future observed-violation
forecasting more robust. They cannot support claims such as minutes saved, delay
avoided, or congestion reduced from the current CSV alone.

## Limitations

- Patrol bias: observations reflect where enforcement or capture devices were present.
- Missing traffic speed: no speed, flow, travel-time, or queue data is present.
- No measured delay: the dataset cannot quantify actual delay.
- No violation duration: records do not say how long each obstruction persisted.
- Partial months: available months may not be complete calendar periods.
- Validation missingness: validation status is incomplete for some records.

## Future extensions

Future work may add OSM, traffic speed, weather, camera detection, STGCN-style
spatiotemporal graph models, and cost or minutes-saved analysis. Cost and
minutes-saved claims should be made only after validation against measured delay
or travel-time data.

## Compliance boundary

ParkWatch must not claim actual measured congestion reduction, minutes saved,
delay avoided, or travel-time improvement from the current official CSV alone.
