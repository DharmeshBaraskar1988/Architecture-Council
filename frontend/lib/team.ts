import "server-only";
import { promises as fs } from "fs";
import path from "path";
import { REPO_DIR, runDir } from "./runs";

// Which LLM each agent is set to use, and which one actually answered: team.json (written when a session
// starts) and usage.json (rewritten on every model call, with the calls still in flight).

export interface ModelUse { model: string; calls: number; ok: number; failed: number; seconds: number; cost: number }
export interface Member {
  agent: string; name: string; role: string; votes: boolean;
  specialty: string; works_on: string;    // what the agent is specialised in, and which rounds it works on
  models: string[];               // configured: main model first, then the fallbacks in order
  used: ModelUse[];               // what was actually called, most calls first
  current: string | null;         // the model working right now (live), else the last one that answered
  working: boolean;               // a call is in flight right now
  fellBack: boolean;              // `current` is not the main model
}
export interface Team { members: Member[]; calls: number; failed: number; cost: number }

interface TeamEntry { name: string; role: string; votes: boolean; models: string[]; specialty?: string; works_on?: string }
interface Call { agent: string; model: string; ok: boolean; seconds: number; cost_usd: number; started?: string }

async function json<T>(file: string): Promise<T | null> {
  try { return JSON.parse(await fs.readFile(file, "utf-8")) as T; } catch { return null; }
}

/** Fallback for sessions started before team.json existed: read the current config/personas.yaml. */
async function teamFromConfig(): Promise<Record<string, TeamEntry>> {
  let text = "";
  try { text = await fs.readFile(path.join(/*turbopackIgnore: true*/ REPO_DIR, "config", "personas.yaml"), "utf-8"); } catch { return {}; }
  const out: Record<string, TeamEntry> = {};
  let cur: string | null = null;
  for (const raw of text.split(/\r?\n/)) {                    // the file may have Windows line endings
    const line = raw.replace(/\s+#.*$/, "");
    const agent = /^ {2}(\w+):\s*$/.exec(line);
    if (agent) { cur = agent[1]; out[cur] = { name: cur, role: "", votes: false, models: [], specialty: "", works_on: "" }; continue; }
    if (!cur) continue;
    const kv = /^ {4}(\w+):\s*(.*)$/.exec(line);
    if (!kv) continue;
    const [, k, v] = kv;
    if (k === "name") out[cur].name = v.trim();
    if (k === "role") out[cur].role = v.trim();
    if (k === "specialty") out[cur].specialty = v.trim().replace(/^"|"$/g, "");
    if (k === "works_on") out[cur].works_on = v.trim().replace(/^"|"$/g, "");
    if (k === "votes") out[cur].votes = v.trim() === "true";
    if (k === "model") out[cur].models.unshift(v.trim());
    if (k === "fallback_model") out[cur].models.push(...v.replace(/[[\]]/g, "").split(",").map((x) => x.trim()).filter(Boolean));
  }
  return out;
}

export async function loadTeam(id: string): Promise<Team | null> {
  const dir = runDir(id);
  if (!dir) return null;
  const config = await teamFromConfig();
  const saved = await json<Record<string, TeamEntry>>(path.join(/*turbopackIgnore: true*/ dir, "team.json"));
  // team.json from older sessions has no specialty: take the words from the current config.
  const team = saved
    ? Object.fromEntries(Object.entries(saved).map(([a, e]) => [a, {
        ...e, specialty: e.specialty || config[a]?.specialty || "", works_on: e.works_on || config[a]?.works_on || "" }]))
    : config;
  const usage = await json<{ per_call: Call[]; active?: Call[]; calls: number; failed: number; cost_usd: number }>(
    path.join(/*turbopackIgnore: true*/ dir, "usage.json"));
  const calls = usage?.per_call ?? [];
  const active = usage?.active ?? [];
  const members: Member[] = Object.entries(team).map(([agent, t]) => {
    const mine = calls.filter((c) => c.agent === agent);
    const byModel = new Map<string, ModelUse>();
    for (const c of mine) {
      const u = byModel.get(c.model) ?? { model: c.model, calls: 0, ok: 0, failed: 0, seconds: 0, cost: 0 };
      u.calls++; if (c.ok) u.ok++; else u.failed++;
      u.seconds += c.seconds ?? 0; u.cost += c.cost_usd ?? 0;
      byModel.set(c.model, u);
    }
    const live = active.filter((c) => c.agent === agent).pop();
    const lastOk = [...mine].reverse().find((c) => c.ok);
    const current = live?.model ?? lastOk?.model ?? null;
    return { agent, name: t.name, role: t.role, votes: t.votes, models: t.models,
             specialty: t.specialty ?? "", works_on: t.works_on ?? "",
             used: [...byModel.values()].sort((a, b) => b.calls - a.calls),
             current, working: Boolean(live), fellBack: Boolean(current && t.models[0] && current !== t.models[0]) };
  });
  return { members, calls: usage?.calls ?? calls.length, failed: usage?.failed ?? calls.filter((c) => !c.ok).length, cost: usage?.cost_usd ?? 0 };
}

const PROVIDERS: Record<string, string> = {
  anthropic: "Anthropic", openai: "OpenAI", gemini: "Google Gemini", groq: "Groq", ollama_chat: "Ollama", ollama: "Ollama", mock: "offline mock",
};
/** "openai/gpt-4.1" → { model: "gpt-4.1", provider: "OpenAI" } */
export function splitModel(m: string): { model: string; provider: string } {
  const at = m.indexOf("/");
  if (at < 0) return { model: m, provider: PROVIDERS[m] ?? "" };
  const p = m.slice(0, at);
  return { model: m.slice(at + 1), provider: PROVIDERS[p] ?? p };
}
