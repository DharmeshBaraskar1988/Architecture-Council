import { execFile } from "child_process";
import { existsSync, promises as fs } from "fs";
import path from "path";
import { NextResponse } from "next/server";
import { appendEvent, readEvents, readNotes, REPO_DIR, runDir, sessionState, signAdr } from "@/lib/runs";

// You sign at the reviewer gate from the room. Only for a run nobody has signed yet
// (the room starts sessions with `--review skip`, so they end waiting for you).
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const dir = runDir(id);
  if (!dir) return NextResponse.json({ error: "bad run id" }, { status: 400 });
  const body = await req.json().catch(() => ({}));
  const decision = body.decision === "override" ? "override" : body.decision === "approve" ? "approve" : null;
  const reason = String(body.reason ?? "").trim().slice(0, 2000);
  if (!decision) return NextResponse.json({ error: "decision must be approve or override" }, { status: 400 });
  if (decision === "override" && !reason) return NextResponse.json({ error: "an override needs a reason" }, { status: 400 });

  const events = await readEvents(id);
  if (!events.some((e) => e.type === "stage.decided")) return NextResponse.json({ error: "the council has not decided yet" }, { status: 409 });
  if (events.some((e) => e.type === "reviewer.signed")) return NextResponse.json({ error: "already signed" }, { status: 409 });
  if ((await sessionState(id)).running) return NextResponse.json({ error: "the session is still finishing" }, { status: 409 });

  const review = { decision, reason, reviewer: "you", auto: false, by: "room" };
  await fs.writeFile(path.join(/*turbopackIgnore: true*/ dir, "review.json"), JSON.stringify(review, null, 2), "utf-8");
  const ev = await appendEvent(id, "reviewer.signed", review);
  await signAdr(id, review, await readNotes(id));
  return NextResponse.json({ ok: true, event: ev, recorded: await recordDecisions(dir) });
}

// The signed record goes to the decision database (backend `council ledger record`), so later
// sessions find it as a precedent. A failure here never undoes the sign-off.
function recordDecisions(dir: string): Promise<boolean> {
  const backend = path.join(/*turbopackIgnore: true*/ REPO_DIR, "backend");
  const exe = process.env.COUNCIL_CLI ?? [path.join(/*turbopackIgnore: true*/ backend, ".venv", "Scripts", "council.exe"),
    path.join(/*turbopackIgnore: true*/ backend, ".venv", "bin", "council")].find((p) => existsSync(p));
  if (!exe) return Promise.resolve(false);
  return new Promise((resolve) => {
    execFile(/*turbopackIgnore: true*/ exe, ["ledger", "record", "--run", dir], { cwd: backend, windowsHide: true, timeout: 60000 },
      (err) => resolve(!err));
  });
}
