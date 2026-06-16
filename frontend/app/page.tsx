import Link from "next/link";

export default function LandingPage() {
  return (
    <main className="landing-page">
      <section className="landing-hero">
        <div className="hero-content">
          <p className="eyebrow">A new lens on parking obstruction risk</p>
          <h1>Discover Bengaluru parking obstruction hotspots</h1>
          <p className="hero-subtitle">
            ParkWatch analyzes official parking violation records to uncover spatial
            clusters, temporal patterns, and simple forecasts of future observed
            violations. It reports an Obstruction Risk Score and Congestion-Risk Proxy,
            not measured congestion or measured delay.
          </p>
          <div className="hero-actions">
            <Link href="/dashboard" className="primary-button">
              Open Dashboard
            </Link>
          </div>
        </div>
        
        <div className="hero-features">
          <div className="feature-card">
            <div className="feature-icon">MAP</div>
            <h3>Spatial Maps</h3>
            <p>Interactive scatter views to explore granular grid cells across the city.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">TIME</div>
            <h3>Temporal Trends</h3>
            <p>Heatmaps and line charts revealing exactly when risks peak.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">NEXT</div>
            <h3>Baseline Forecasts</h3>
            <p>Graph-enhanced baseline forecasts for future observed parking violations.</p>
          </div>
        </div>
      </section>
    </main>
  );
}
