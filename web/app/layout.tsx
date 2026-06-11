import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "VFIED — Behaviour Evaluation Platform",
  description: "Bring your own AI. VFIED tests the behaviour.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <aside className="sidebar">
            <div className="brand">VFIED</div>
            <div className="tagline">Bring your own AI.<br />VFIED tests the behaviour.</div>
            <nav>
              <a href="/projects">Projects</a>
              <a href="#" className="disabled" title="v2">Drift Explorer · v2</a>
              <a href="#" className="disabled" title="v2">Cue Activity · v2</a>
              <a href="#" className="disabled" title="v2">Leaderboards · v2</a>
            </nav>
          </aside>
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
