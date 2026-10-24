import Link from "next/link";
import { notFound } from "next/navigation";
import { loadRun, readDocument, readNotes, sessionState } from "@/lib/runs";
import Room from "./Room";

export const dynamic = "force-dynamic";

export default async function RoomPage({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ turn?: string }>;
}) {
  const { id } = await params;
  const { turn } = await searchParams;
  const run = await loadRun(id);
  if (!run) notFound();
  const [state, notes, document] = await Promise.all([sessionState(id), readNotes(id), readDocument(id)]);
  return (
    <main className="wrap wide">
      <div className="topbar">
        <Link href="/">← Sessions</Link>
        <h1>Council room</h1>
        <span className="muted">{run.document ?? state.prd ?? "starting…"}</span>
      </div>
      <Room id={id} initial={run.log} names={run.names} decision={run.decision} notes={notes} running={state.running}
            document={document}
            startTurn={turn === "end" ? Number.MAX_SAFE_INTEGER : turn ? Math.max(0, Number(turn) - 1) : -1} />
    </main>
  );
}
