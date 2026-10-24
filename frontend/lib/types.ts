// Shapes of the files a council run writes (backend/app/schemas.py and the run folder).

export type Stance = "adopt" | "adopt_with_condition" | "reject";
export type Verdict = "verified" | "partly_supports" | "unverified" | "contradicted";

export interface CouncilEvent {
  seq: number;
  type: string;
  session: string;
  stage: string;
  payload: Record<string, any>;
  at: string;
}

export interface BoardRow {
  subject: string;
  name?: string;
  outcome: string;
  agreement: number | null;
  vote_support: number | null;
  evidence_balance: number | null;
  reasons: string[];
  flags: string[];
  revoted: boolean;
  guardrail: string | null;
  votes: { agent: string; stance: Stance; confidence: number; convinced_by: string; condition: string | null }[];
  open_objections: string[];
}

export interface Decision {
  stage: string;
  stage_agreement: number | null;
  statement: string;
  statement_by: string;
  board: BoardRow[];
  revote: { subjects: string[]; compromises: Record<string, string> };
}

export interface RunSummary {
  id: string;
  document: string | null;
  startedAt: string | null;
  stageAgreement: number | null;
  outcomes: Record<string, number>;
  costUsd: number | null;
  events: number;
  complete: boolean;
}

export interface RunDetail extends RunSummary {
  log: CouncilEvent[];
  decision: Decision | null;
  names: Record<string, string>;
  usage: { calls: number; failed: number; cost_usd: number } | null;
}
