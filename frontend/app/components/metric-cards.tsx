import React from 'react';
import { Card, CardContent, Typography, Grid } from '@mui/material';
import type { Hotspot, StationSummary, Summary } from "../lib/types";

type MetricCardsProps = {
  summary: Summary;
  stations: StationSummary[];
  hotspots: Hotspot[];
};

export function MetricCards({ summary, stations, hotspots }: MetricCardsProps) {
  const topRisk = hotspots[0]?.obstruction_risk_score ?? 0;
  const highConfidence = hotspots.filter((item) => item.confidence === "High").length;
  const leadingStation = stations[0]?.station ?? "Unavailable";

  const metrics = [
    {
      title: "Total violations",
      value: summary.total_violations.toLocaleString("en-IN"),
      subtitle: "Official CSV records aggregated into hotspot cells",
      color: "primary.main"
    },
    {
      title: "Top score",
      value: topRisk.toFixed(1),
      subtitle: "Highest Obstruction Risk Score in current ranking",
      color: "error.main"
    },
    {
      title: "High confidence",
      value: highConfidence.toLocaleString("en-IN"),
      subtitle: "Hotspots with repeated evidence and device-day support",
      color: "success.main"
    },
    {
      title: "Leading station",
      value: leadingStation,
      subtitle: "Station with the highest aggregated violation count",
      color: "warning.main",
      isText: true
    }
  ];

  return (
    <Grid container spacing={3} sx={{ mb: 4 }} aria-label="Key metrics">
      {metrics.map((metric, index) => (
        <Grid size={{ xs: 12, sm: 6, md: 3 }} key={index}>
          <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: 'background.paper', borderRadius: 3, transition: 'transform 0.2s', '&:hover': { transform: 'translateY(-4px)' } }}>
            <CardContent sx={{ flexGrow: 1, p: 3 }}>
              <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 600, letterSpacing: 1 }}>
                {metric.title}
              </Typography>
              <Typography 
                variant={metric.isText ? "h5" : "h3"} 
                component="div" 
                sx={{ mt: 1, mb: 1, fontWeight: 700, color: metric.color }}
              >
                {metric.value}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.4 }}>
                {metric.subtitle}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      ))}
    </Grid>
  );
}
