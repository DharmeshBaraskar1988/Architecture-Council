import { NextResponse } from "next/server";
import { addNote, runDir } from "@/lib/runs";

// "Raise your hand": what you say at the table goes on the run's record for the reviewer.
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!runDir(id)) return NextResponse.json({ error: "bad run id" }, { status: 400 });
  const body = await req.json().catch(() => ({}));
  const text = String(body.text ?? "").trim();
  if (!text) return NextResponse.json({ error: "empty note" }, { status: 400 });
  const note = await addNote(id, text, Math.max(0, Number(body.afterSeq) || 0));
  return NextResponse.json({ ok: true, note });
}
