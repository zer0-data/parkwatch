import Link from "next/link";

export default function LandingPage() {
  return (
    <main className="landing-page">
      <section className="landing-hero">
        <div className="hero-content">
          <p className="eyebrow">AI-powered parking enforcement intelligence</p>
          <h1>Plan targeted patrols for Bengaluru parking pressure.</h1>
          <p className="hero-subtitle">
            ParkWatch turns official parking violation records into hotspot maps,
            GraphSAGE forecasts, A*-optimized patrol sequences, and exportable action
            reports for traffic enforcement teams.
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
            <h3>Hotspot intelligence</h3>
            <p>Interactive maps reveal repeated illegal-parking pressure zones.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">TIME</div>
            <h3>Peak-window targeting</h3>
            <p>Temporal heatmaps show when enforcement is most likely to matter.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">NEXT</div>
            <h3>Forecast patrol plans</h3>
            <p>GraphSAGE forecasts feed an A* sequence for priority patrol stops.</p>
          </div>
        </div>
      </section>
    </main>
  );
}
