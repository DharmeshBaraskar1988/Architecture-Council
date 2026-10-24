import { NextResponse } from "next/server";
import { loadTeam, splitModel } from "@/lib/team";

export const dynamic = "force-dynamic";

// Who is at the table and which LLM each one is using (live while a session runs).
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const team = await loadTeam(id);
  if (!team) return NextResponse.json({ error: "no such run" }, { status: 404 });
  return NextResponse.json({
    ...team,
    members: team.members.map((m) => ({ ...m, currentLabel: m.current ? splitModel(m.current) : null })),
  });
}
