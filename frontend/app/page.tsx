import Link from "next/link";
import { listRuns, RUNS_DIR } from "@/lib/runs";
import { OUTCOME_LABEL } from "@/lib/replay";
import NewSession from "./NewSession";

export const dynamic = "force-dynamic"; // new sessions appear on reload

export default async function Home() {
  const runs = await listRuns();
  return (
    <main className="wrap">
      <h1>Architecture Council</h1>
      <p className="muted">Sit at the table: the council debates a product document, and you have the last word.</p>
      <NewSession />

      <h2 style={{ marginTop: 28 }}>Sessions</h2>
      {runs.length === 0 ? (
        <p className="empty">No sessions yet in {RUNS_DIR}.</p>
      ) : (
        <div className="runs">
          {runs.map((r) => (
            <div key={r.id} className="panel run-row">
              <div>
                <h3><Link href={`/runs/${r.id}/room`}>{r.document ?? "Starting…"}</Link></h3>
                <div className="mono muted">{r.id}</div>
                <div className="meta">
                  {r.complete ? <span className="chip accent">decided</span> : <span className="chip warn">in progress or stopped</span>}
                  {Object.entries(r.outcomes).map(([o, n]) => <span key={o} className="chip">{n} × {OUTCOME_LABEL[o] ?? o}</span>)}
                  {r.costUsd !== null && <span className="chip">${r.costUsd.toFixed(3)}</span>}
                </div>
                <div className="meta">
                  <Link href={`/runs/${r.id}/room`}>Enter the room →</Link>
                  <Link href={`/runs/${r.id}`} className="muted">board view</Link>
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                {r.stageAgreement !== null ? (
                  <><div className="big">{Math.round(r.stageAgreement)}%</div><div className="muted" style={{ fontSize: 12 }}>stage agreement</div></>
                ) : <span className="muted">no decision yet</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
