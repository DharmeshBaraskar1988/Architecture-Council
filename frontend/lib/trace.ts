import "server-only";
import { promises as fs } from "fs";
import path from "path";
import { runDir } from "./runs";

// Everything a run recorded about who did what: facts (Mira), cards (voters), verdicts (Vera),
// challenges (another voter), rebuttals (the author), votes (every voter) and the result (code).
// Read straight from the run folder; nothing here is recomputed.

export interface TFact { id: string; key: string; value: unknown; status: string; page: number | null; quote: string | null; note: string | null }
export interface TCard { id: string; agent: string; subject: string; stance: string; claim: string; facts: string[]; condition: string | null;
  weight: number | null; removed: boolean; conceded: boolean; thinking?: string | null; issues: string[] }
export interface TCheck { card: string; ref: string; verdict: string; weight: number | null; by: string; note: string | null; side: string }
export interface TChallenge { id: string; agent: string; target: string; target_agent: string; target_subject: string; type: string; text: string;
  facts: string[]; weight: number | null; answered?: boolean; counter_case: boolean; removed: boolean; thinking?: string | null }
export interface TRebuttal { id: string; agent: string; challenge: string; target: string; subject: string; response: string; text: string;
  facts: string[]; weight: number | null; thinking?: string | null }
export interface TVote { agent: string; subject: string; stance: string; confidence: number; convinced_by: string; condition: string | null;
  thinking?: string | null; issues?: string[] }
export interface TRow { subject: string; name?: string; outcome: string; agreement: number | null; vote_support: number | null;
  evidence_balance: number | null; reasons: string[]; flags: string[]; guardrail: string | null; revoted: boolean }

export interface Trace {
  document: string | null;
  facts: TFact[];
  shortlist: { id: string; name: string; status: string; reason: string; facts_used: string[] }[];
  cards: TCard[];
  cardChecks: TCheck[];
  challenges: TChallenge[];
  challengeChecks: TCheck[];
  assigned: Record<string, string[]>;
  rebuttals: TRebuttal[];
  votes: TVote[];          // R6, blind
  revotes: TVote[];        // R7 re-vote: replaces that voter's R6 vote on the subject
  compromises: Record<string, string>;
  board: TRow[];
  stageAgreement: number | null;
  review: { decision: string; reason: string; reviewer?: string; auto?: boolean; by?: string } | null;
  names: Record<string, string>;
}

async function json<T>(dir: string, file: string): Promise<T | null> {
  try {
    return JSON.parse(await fs.readFile(path.join(/*turbopackIgnore: true*/ dir, file), "utf-8")) as T;
  } catch {
    return null;
  }
}

export async function loadTrace(id: string): Promise<Trace | null> {
  const dir = runDir(id);
  if (!dir) return null;
  const [sheet, shortlist, proposals, factcheck, chs, rebs, votes, decision, review] = await Promise.all([
    json<{ document: string; facts: TFact[] }>(dir, "fact_sheet.json"),
    json<Trace["shortlist"]>(dir, "applicability.json"),
    json<{ cards: TCard[] }>(dir, "proposals.json"),
    json<{ checks: TCheck[]; cards: { id: string; weight: number | null; removed: boolean }[] }>(dir, "factcheck.json"),
    json<{ challenges: TChallenge[]; checks: TCheck[]; assigned: Record<string, string[]> }>(dir, "challenges.json"),
    json<{ rebuttals: TRebuttal[]; conceded_cards: string[]; challenges_answered: string[] }>(dir, "rebuttals.json"),
    json<{ votes: TVote[] }>(dir, "votes.json"),
    json<{ board: TRow[]; stage_agreement: number | null; revote: { votes: TVote[]; compromises: Record<string, string> } }>(dir, "strategy_decision.json"),
    json<Trace["review"]>(dir, "review.json"),
  ]);
  if (!sheet) return null;
  // Cards as they ended up: weight and removal from R3, concessions from R5.
  const weighed = Object.fromEntries((factcheck?.cards ?? []).map((c) => [c.id, c]));
  const conceded = new Set(rebs?.conceded_cards ?? []);
  const answered = new Set(rebs?.challenges_answered ?? []);
  const names: Record<string, string> = { build_approach: "Build approach", delivery_path: "Delivery path" };
  for (const s of shortlist ?? []) names[s.id] = s.name;
  return {
    document: sheet.document,
    facts: sheet.facts,
    shortlist: shortlist ?? [],
    cards: (proposals?.cards ?? []).map((c) => ({ ...c, weight: weighed[c.id]?.weight ?? c.weight ?? null,
                                                    removed: weighed[c.id]?.removed ?? false, conceded: conceded.has(c.id) })),
    cardChecks: factcheck?.checks ?? [],
    challenges: (chs?.challenges ?? []).map((c) => ({ ...c, answered: answered.has(c.id) })),
    challengeChecks: chs?.checks ?? [],
    assigned: chs?.assigned ?? {},
    rebuttals: rebs?.rebuttals ?? [],
    votes: votes?.votes ?? [],
    revotes: decision?.revote?.votes ?? [],
    compromises: decision?.revote?.compromises ?? {},
    board: decision?.board ?? [],
    stageAgreement: decision?.stage_agreement ?? null,
    review,
    names,
  };
}

/** Who wrote the item a vote was convinced by: "agent:subject" card, "a>b:subject" challenge,
 *  "re:..." rebuttal, "compromise:subject" (the Moderator's). */
export function authorOf(ref: string, t: Trace): { agent: string | null; kind: string; text: string | null } {
  if (ref.startsWith("compromise:")) return { agent: "moderator", kind: "compromise", text: t.compromises[ref.slice(11)] ?? null };
  if (ref.startsWith("re:")) {
    const r = t.rebuttals.find((x) => x.id === ref);
    return { agent: r?.agent ?? null, kind: r?.response === "concede" ? "concession" : "rebuttal", text: r?.text ?? null };
  }
  if (ref.includes(">")) {
    const c = t.challenges.find((x) => x.id === ref);
    return { agent: c?.agent ?? ref.split(">")[0], kind: c?.counter_case ? "counter-case" : "challenge", text: c?.text ?? null };
  }
  const card = t.cards.find((x) => x.id === ref);
  return { agent: card?.agent ?? (ref.includes(":") ? ref.split(":")[0] : null), kind: "argument", text: card?.claim ?? null };
}

/** Final votes on a subject: the R7 re-vote where a voter re-voted, otherwise their R6 vote. */
export function finalVotes(subject: string, t: Trace): (TVote & { revoted: boolean; before?: TVote })[] {
  const first = t.votes.filter((v) => v.subject === subject);
  const again = t.revotes.filter((v) => v.subject === subject);
  const out = first.map((v) => {
    const r = again.find((x) => x.agent === v.agent);
    return r ? { ...r, revoted: true, before: v } : { ...v, revoted: false };
  });
  for (const r of again) if (!first.some((v) => v.agent === r.agent)) out.push({ ...r, revoted: true });
  return out;
}
