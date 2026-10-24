import { NextResponse } from "next/server";
import { loadRun, readDocument, readNotes, sessionState } from "@/lib/runs";

export const dynamic = "force-dynamic";

// The room polls this while a session runs: new events since `after`, plus what the script needs.
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const after = Math.max(0, Number(new URL(req.url).searchParams.get("after")) || 0);
  const run = await loadRun(id);
  if (!run) return NextResponse.json({ error: "no such run" }, { status: 404 });
  const [state, notes, document] = await Promise.all([sessionState(id), readNotes(id), readDocument(id)]);
  return NextResponse.json({
    events: run.log.slice(after), total: run.log.length, running: state.running,
    names: run.names, decision: run.decision, notes, document,
  });
}
