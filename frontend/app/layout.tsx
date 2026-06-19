import type { Metadata } from "next";
import Link from "next/link";
import "./styles.css";
import ThemeRegistry from "./ThemeRegistry";

export const metadata: Metadata = {
  title: "ParkWatch",
  description: "Civic-tech dashboard for parking obstruction risk hotspots"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <div className="noise-overlay"></div>
        <header className="app-header">
          <Link className="brand" href="/">
            <span className="brand-mark">PW</span>
            <span>
              <strong>ParkWatch</strong>
              <small>Obstruction Risk Score</small>
            </span>
          </Link>
          <nav aria-label="Primary navigation">
            <Link className="nav-primary" href="/dashboard">Dashboard</Link>
            <Link href="/explainer">Explainer</Link>
            <Link href="/methodology">Methodology</Link>
          </nav>
        </header>
        <ThemeRegistry>
          {children}
        </ThemeRegistry>
      </body>
    </html>
  );
}
