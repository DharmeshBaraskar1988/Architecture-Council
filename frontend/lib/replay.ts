// Rebuilds what the council room looks like after the first `n` events of a run.
// Pure: the same log and position always give the same picture, so play, pause, step and seek
// are just different values of `n`.
import type { CouncilEvent, Stance, Verdict } from "./types";

export const ROUNDS = ["R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "Gate"] as const;
export type Round = (typeof ROUNDS)[number];

export const ROUND_TITLES: Record<Round, string> = {
  R0: "Fact sheet", R1: "Shortlist", R2: "Proposals", R3: "Fact check", R4: "Challenges",
  R5: "Rebuttals", R6: "Vote", R7: "Converge", Gate: "Reviewer",
};

export const AGENTS: Record<string, { name: string; role: string; color: string }> = {
  moderator: { name: "Mira", role: "Moderator", color: "var(--c-mod)" },
  strategist: { name: "Tara", role: "Strategist", color: "var(--c-str)" },
  architect: { name: "Ada", role: "Architect", color: "var(--c-arch)" },
  platform_cost: { name: "Kabir", role: "Platform & Cost", color: "var(--c-cloud)" },
  critic: { name: "Rex", role: "Critic", color: "var(--c-critic)" },
  fact_checker: { name: "Vera", role: "Fact checker", color: "var(--c-fact)" },
};
export const VOTERS = ["strategist", "architect", "platform_cost", "critic"];

/** Which round an event belongs to. Verdicts belong to the round of what they check. */
export function roundOf(e: CouncilEvent): Round {
  switch (e.type) {
    case "session.started": case "fact.extracted": case "factsheet.ready": return "R0";
    case "shortlist.ready": return "R1";
    case "card.proposed": return "R2";
    case "factcheck.verdict": {
      const card = String(e.payload.card ?? "");
      return card.startsWith("re:") ? "R5" : card.includes(">") ? "R4" : "R3";
    }
    case "challenge.raised": return "R4";
    case "rebuttal.made": return "R5";
    case "vote.cast": return e.payload.revote ? "R7" : "R6";
    case "consensus.result": case "stage.decided": return "R7";
    case "reviewer.signed": return "Gate";
    case "error": case "round.started": return (e.payload.round as Round) ?? "R0";
    default: return "R0";
  }
}

export interface Fact { id: string; key: string; value: unknown; status: string; page: number | null; quote: string | null; note: string | null }
export interface ShortItem { id: string; name: string; status: string; reason: string; depends_on_assumption: boolean }
export interface Card {
  id: string; agent: string; subject: string; stance: Stance; claim: string; facts: string[];
  condition: string | null; issues: string[]; weight: number | null; removed: boolean; conceded: boolean;
}
export interface Check { card: string; ref: string; verdict: Verdict; weight: number | null; by: string; note: string | null; side: string }
export interface Challenge {
  id: string; agent: string; target: string; target_subject: string; target_agent: string; challenge_type: string;
  text: string; facts: string[]; weight: number | null; counter_case: boolean; removed: boolean;
}
export interface Rebuttal { id: string; agent: string; challenge: string; target: string; subject: string; response: "rebut" | "concede" | "revise"; text: string; weight: number | null }
export interface VoteCast { agent: string; subject: string; stance: Stance; confidence: number; convinced_by: string; condition: string | null; revote: boolean }
export interface Result {
  subject: string; name?: string; outcome: string; agreement: number | null; vote_support: number | null;
  evidence_balance: number | null; reasons: string[]; flags: string[]; guardrail: string | null; revoted: boolean;
}

export interface Snapshot {
  document: string | null;
  facts: Fact[];
  shortlist: ShortItem[];
  cards: Card[];
  checks: Check[];
  challenges: Challenge[];
  rebuttals: Rebuttal[];
  votes: VoteCast[];          // R6, blind
  revotes: VoteCast[];        // R7 compromise re-vote; replaces that voter's R6 vote on the subject
  results: Result[];
  statement: string | null;
  stageAgreement: number | null;
  signed: { decision: string; reason: string; auto: boolean } | null;
  errors: { round: string; agent: string; error: string }[];
  round: Round;
}

export function snapshot(log: CouncilEvent[], n: number): Snapshot {
  const s: Snapshot = {
    document: null, facts: [], shortlist: [], cards: [], checks: [], challenges: [], rebuttals: [], votes: [],
    revotes: [], results: [], statement: null, stageAgreement: null, signed: null, errors: [], round: "R0",
  };
  const cards = new Map<string, Card>();
  const chs = new Map<string, Challenge>();
  for (const e of log.slice(0, n)) {
    const p = e.payload;
    s.round = roundOf(e);
    switch (e.type) {
      case "session.started": s.document = p.document; break;
      case "fact.extracted": s.facts.push(p as Fact); break;
      case "shortlist.ready": s.shortlist = p.items as ShortItem[]; break;
      case "card.proposed":
        cards.set(p.id, { ...(p as Card), weight: null, removed: false, conceded: false });
        break;
      case "factcheck.verdict": {
        s.checks.push(p as Check);
        const c = cards.get(p.card);
        if (c) {                                            // weights grow as each verdict lands
          c.weight = Math.round(((c.weight ?? 0) + (p.weight ?? 0)) * 100) / 100;
          if (p.verdict === "contradicted") c.removed = true;
        }
        break;
      }
      case "challenge.raised": chs.set(p.id, p as Challenge); break;
      case "rebuttal.made": {
        s.rebuttals.push(p as Rebuttal);
        const c = cards.get(p.target);
        if (c && p.response === "concede") c.conceded = true;
        break;
      }
      case "vote.cast": {
        const v = { ...(p as VoteCast), revote: Boolean(p.revote) };
        (v.revote ? s.revotes : s.votes).push(v);
        break;
      }
      case "consensus.result": s.results.push(p as Result); break;
      case "stage.decided": s.statement = p.statement; s.stageAgreement = p.stage_agreement; break;
      case "reviewer.signed": s.signed = p as Snapshot["signed"]; break;
      case "error": s.errors.push({ round: p.round, agent: p.agent, error: p.error }); break;
    }
  }
  s.cards = [...cards.values()];
  s.challenges = [...chs.values()];
  return s;
}

/** Index just after the last event of each round, for the round stepper. */
export function roundEnds(log: CouncilEvent[]): Partial<Record<Round, number>> {
  const out: Partial<Record<Round, number>> = {};
  log.forEach((e, i) => { out[roundOf(e)] = i + 1; });
  return out;
}

/** How long each event stays on screen at 1x, in ms. Quick for bulk events, slower for decisions. */
export function dwell(e: CouncilEvent): number {
  switch (e.type) {
    case "fact.extracted": return 180;
    case "factcheck.verdict": return 60;
    case "card.proposed": case "challenge.raised": case "rebuttal.made": return 260;
    case "vote.cast": return 120;
    case "consensus.result": return 700;
    case "shortlist.ready": case "stage.decided": return 1600;
    default: return 400;
  }
}

export const STANCE_SHORT: Record<Stance, string> = { adopt: "adopt", adopt_with_condition: "cond", reject: "reject" };
export const VERDICT_MARK: Record<Verdict, string> = { verified: "✓", partly_supports: "½", unverified: "?", contradicted: "✗" };
export const OUTCOME_LABEL: Record<string, string> = {
  selected: "Selected", selected_with_condition: "Selected with condition", reviewer_decides: "Reviewer decides",
  rejected: "Rejected", parked: "Parked", not_applicable: "Not applicable",
};
