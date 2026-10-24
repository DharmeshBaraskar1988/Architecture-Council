import { NextResponse } from "next/server";
import { avatarStatus, queueAvatars, type AvatarLine } from "@/lib/avatars";
import { runDir } from "@/lib/runs";
import { EDGE_VOICE } from "@/lib/voice";

const SPEAKERS = new Set(Object.keys(EDGE_VOICE));

// Talking-head videos for a session: GET reports progress, POST queues the room's spoken lines for rendering.
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!runDir(id)) return NextResponse.json({ error: "bad run id" }, { status: 400 });
  return NextResponse.json(await avatarStatus(id));
}

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!runDir(id)) return NextResponse.json({ error: "bad run id" }, { status: 400 });
  const body = await req.json().catch(() => null);
  if (!Array.isArray(body?.lines) || body.lines.length > 2000) return NextResponse.json({ error: "lines must be a list" }, { status: 400 });
  const lines: AvatarLine[] = [];
  for (const l of body.lines) {
    const text = typeof l?.text === "string" ? l.text.trim() : "";
    if (!SPEAKERS.has(l?.speaker) || l.voice !== EDGE_VOICE[l.speaker as keyof typeof EDGE_VOICE] || !text || text.length > 4000)
      return NextResponse.json({ error: "each line needs a member, that member's voice and 1 to 4000 characters" }, { status: 400 });
    lines.push({ speaker: l.speaker, voice: l.voice, text });
  }
  return NextResponse.json(await queueAvatars(id, lines));
}
