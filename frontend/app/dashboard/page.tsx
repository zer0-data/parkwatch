import { DashboardShell } from "../components/dashboard-shell";
import { getDashboardData } from "../lib/api";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  try {
    const data = await getDashboardData();
    return <DashboardShell {...data} />;
  } catch (error) {
    return (
      <main className="page-shell">
        <section className="hero-band">
          <div>
            <p className="eyebrow">ParkWatch backend</p>
            <h1>Dashboard data is not available yet.</h1>
            <p>
              Start the FastAPI backend and make sure preprocessing has generated the
              JSON outputs. ParkWatch needs the precomputed hotspot, forecast, and
              patrol-planning data before the command dashboard can load.
            </p>
          </div>
        </section>
        <section className="status-card" role="alert">
          <strong>Request failed</strong>
          <span>{error instanceof Error ? error.message : "Unknown backend error"}</span>
        </section>
      </main>
    );
  }
}
