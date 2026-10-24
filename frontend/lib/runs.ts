import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { CouncilEvent, Decision, RunDetail, RunSummary } from "./types";

// data/runs next to this folder, unless COUNCIL_RUNS_DIR says otherwise.
export const RUNS_DIR = process.env.COUNCIL_RUNS_DIR ?? path.resolve(/*turbopackIgnore: true*/ process.cwd(), "..", "data", "runs");

const RUN_ID = /^[\w-]+$/; // run folder names only: no path traversal through the URL

async function readJson<T>(file: string): Promise<T | null> {
  try {
    return JSON.parse(await fs.readFile(file, "utf-8")) as T;
  } catch {
    return null;
  }
}

async function readLog(dir: string): Promise<CouncilEvent[]> {
  try {
    const text = await fs.readFile(path.join(/*turbopackIgnore: true*/ dir, "debate_log.jsonl"), "utf-8");
    return text
      .split("\n")
      .filter((l) => l.trim())
      .map((l) => JSON.parse(l) as CouncilEvent)
      .sort((a, b) => a.seq - b.seq);
  } catch {
    return [];
  }
}

async function summarise(id: string, log?: CouncilEvent[]): Promise<RunSummary> {
  const dir = path.join(/*turbopackIgnore: true*/ RUNS_DIR, id);
  const [sheet, decision, usage, events] = await Promise.all([
    readJson<{ document: string }>(path.join(/*turbopackIgnore: true*/ dir, "fact_sheet.json")),
    readJson<Decision>(path.join(/*turbopackIgnore: true*/ dir, "strategy_decision.json")),
    readJson<{ cost_usd: number }>(path.join(/*turbopackIgnore: true*/ dir, "usage.json")),
    log ? Promise.resolve(log) : readLog(dir),
  ]);
  const outcomes: Record<string, number> = {};
  for (const r of decision?.board ?? []) outcomes[r.outcome] = (outcomes[r.outcome] ?? 0) + 1;
  return {
    id,
    document: sheet?.document ?? null,
    startedAt: events[0]?.at ?? null,
    stageAgreement: decision?.stage_agreement ?? null,
    outcomes,
    costUsd: usage?.cost_usd ?? null,
    events: events.length,
    complete: events.some((e) => e.type === "stage.decided"),
  };
}

export async function listRuns(): Promise<RunSummary[]> {
  let names: string[] = [];
  try {
    const entries = await fs.readdir(RUNS_DIR, { withFileTypes: true });
    names = entries.filter((e) => e.isDirectory() && RUN_ID.test(e.name)).map((e) => e.name);
  } catch {
    return [];
  }
  names.sort().reverse(); // folder names start with the date and time
  return Promise.all(names.map((n) => summarise(n)));
}

export const REPO_DIR = path.resolve(/*turbopackIgnore: true*/ process.cwd(), "..");
export const UPLOADS_DIR = path.join(/*turbopackIgnore: true*/ REPO_DIR, "data", "uploads");

export function runDir(id: string): string | null {
  return RUN_ID.test(id) ? path.join(/*turbopackIgnore: true*/ RUNS_DIR, id) : null;
}

export async function readEvents(id: string, after = 0): Promise<CouncilEvent[]> {
  const dir = runDir(id);
  return dir ? (await readLog(dir)).slice(after) : [];
}

/** Append one event to a run's log, the same shape the backend's EventBus writes. */
export async function appendEvent(id: string, type: string, payload: Record<string, unknown>): Promise<CouncilEvent> {
  const dir = runDir(id);
  if (!dir) throw new Error("bad run id");
  const log = await readLog(dir);
  const ev: CouncilEvent = { seq: (log[log.length - 1]?.seq ?? 0) + 1, type, session: id, stage: "strategy", payload,
                             at: new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00") };
  await fs.appendFile(path.join(/*turbopackIgnore: true*/ dir, "debate_log.jsonl"), JSON.stringify(ev) + "\n", "utf-8");
  return ev;
}

export interface Note { text: string; afterSeq: number; at: string }

export async function readNotes(id: string): Promise<Note[]> {
  const dir = runDir(id);
  if (!dir) return [];
  try {
    return (await fs.readFile(path.join(/*turbopackIgnore: true*/ dir, "reviewer_notes.jsonl"), "utf-8"))
      .split("\n").filter((l) => l.trim()).map((l) => JSON.parse(l) as Note);
  } catch {
    return [];
  }
}

export async function addNote(id: string, text: string, afterSeq: number): Promise<Note> {
  const dir = runDir(id);
  if (!dir) throw new Error("bad run id");
  const note: Note = { text: text.slice(0, 2000), afterSeq, at: new Date().toISOString() };
  await fs.appendFile(path.join(/*turbopackIgnore: true*/ dir, "reviewer_notes.jsonl"), JSON.stringify(note) + "\n", "utf-8");
  return note;
}

export interface DocSection { number: number; title: string | null; text: string }

/** The document as the council read it, section by section (written at R0). */
export async function readDocument(id: string): Promise<{ name: string; sections: DocSection[] } | null> {
  const dir = runDir(id);
  return dir ? readJson(path.join(/*turbopackIgnore: true*/ dir, "document.json")) : null;
}

/** The strategy ADR (written at R7), with the sign-off filled in when the reviewer has signed. */
export async function readAdr(id: string): Promise<string | null> {
  const dir = runDir(id);
  if (!dir) return null;
  try {
    return await fs.readFile(path.join(/*turbopackIgnore: true*/ dir, "strategy_adr.md"), "utf-8");
  } catch {
    return null;
  }
}

/** Same as backend app/docs/adr.py with_signoff: replace the pending sign-off with the decision and notes. */
export async function signAdr(id: string, review: { decision: string; reason: string; reviewer: string }, notes: Note[]): Promise<void> {
  const dir = runDir(id);
  const adr = await readAdr(id);
  if (!dir || !adr) return;
  const lines = [`**${review.decision === "approve" ? "Approved" : "Overridden"}** by ${review.reviewer}, in the council room.`];
  if (review.reason) lines.push(`Reason: ${review.reason}`);
  if (notes.length) lines.push("", "Notes raised during the session:", ...notes.map((n) => `- ${n.text}`));
  await fs.writeFile(path.join(/*turbopackIgnore: true*/ dir, "strategy_adr.md"),
                     adr.replace("## Reviewer sign-off\n\n_Pending._", "## Reviewer sign-off\n\n" + lines.join("\n")), "utf-8");
}

/** Is the backend process that writes this run still going? (session.json is written when the room starts it.) */
export async function sessionState(id: string): Promise<{ running: boolean; prd: string | null }> {
  const dir = runDir(id);
  const s = dir ? await readJson<{ pid: number; prd: string }>(path.join(/*turbopackIgnore: true*/ dir, "session.json")) : null;
  if (!s) return { running: false, prd: null };
  // The CLI's last line says the run is saved: then it is over, whatever process now has that id
  // (Windows reuses process ids, so the id alone can make a finished session look live).
  try {
    const out = await fs.readFile(path.join(/*turbopackIgnore: true*/ dir!, "console.log"), "utf-8");
    if (out.includes("Run saved to ")) return { running: false, prd: s.prd };
  } catch { /* no console yet: still starting */ }
  try {
    process.kill(s.pid, 0);               // signal 0 only tests that the process exists
    return { running: true, prd: s.prd };
  } catch {
    return { running: false, prd: s.prd };
  }
}

export async function loadRun(id: string): Promise<RunDetail | null> {
  if (!RUN_ID.test(id)) return null;
  const dir = path.join(/*turbopackIgnore: true*/ RUNS_DIR, id);
  try {
    if (!(await fs.stat(dir)).isDirectory()) return null;
  } catch {
    return null;
  }
  const log = await readLog(dir);
  const [summary, decision, applicability, usage] = await Promise.all([
    summarise(id, log),
    readJson<Decision>(path.join(/*turbopackIgnore: true*/ dir, "strategy_decision.json")),
    readJson<{ id: string; name: string }[]>(path.join(/*turbopackIgnore: true*/ dir, "applicability.json")),
    readJson<RunDetail["usage"]>(path.join(/*turbopackIgnore: true*/ dir, "usage.json")),
  ]);
  const names: Record<string, string> = { build_approach: "Build approach", delivery_path: "Delivery path" };
  for (const a of applicability ?? []) names[a.id] = a.name;
  return { ...summary, log, decision, names, usage };
}
