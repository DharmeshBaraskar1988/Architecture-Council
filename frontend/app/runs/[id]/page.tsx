import Link from "next/link";
import { notFound } from "next/navigation";
import { loadRun } from "@/lib/runs";
import Replay from "./Replay";

export const dynamic = "force-dynamic";

export default async function RunPage({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ at?: string }>;
}) {
  const { id } = await params;
  const { at } = await searchParams;
  const run = await loadRun(id);
  if (!run) notFound();
  return (
    <main className="wrap">
      <div className="topbar">
        <Link href="/">← Runs</Link>
        <h1>{run.document ?? run.id}</h1>
        <span className="mono muted">{run.id}</span>
        {run.usage && (
          <span className="muted">
            {run.usage.calls} model calls · {run.usage.failed} failed · ${run.usage.cost_usd.toFixed(3)}
          </span>
        )}
      </div>
      {run.log.length === 0 ? (
        <p className="empty">This run has no event log.</p>
      ) : (
        <Replay id={id} log={run.log} names={run.names} fromUrl={at !== undefined}
                start={at === "end" ? run.log.length : Math.max(0, Math.min(Number(at) || 0, run.log.length))} />
      )}
    </main>
  );
}
