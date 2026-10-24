// Turns a run's event log into a conversation at the table: who speaks, what they say in plain
// words (this is also what the voice reads), and the evidence card that goes on the table.
// Pure: the same events always give the same lines, so a live run just appends more lines.
import type { CouncilEvent, Decision } from "./types";
import { roundOf, type Round } from "./replay";

export type Speaker = "moderator" | "strategist" | "architect" | "platform_cost" | "critic" | "fact_checker" | "you";

export type TableCard =
  | { kind: "fact"; id: string; label: string; value: string; status: string; quote: string | null; page: number | null; note: string | null }
  | { kind: "shortlist"; items: { id: string; name: string; status: string; reason: string }[] }
  | { kind: "argument"; agent: string; subject: string; stance: string; claim: string; facts: string[]; condition: string | null; issues: string[] }
  | { kind: "check"; subject: string; rows: { agent: string; weight: number; marks: { ref: string; verdict: string; note: string | null }[] }[] }
  | { kind: "challenge"; agent: string; target: string; subject: string; type: string; text: string; weight: number | null; counter: boolean; facts: string[] }
  | { kind: "rebuttal"; agent: string; subject: string; response: string; text: string; weight: number | null; facts: string[] }
  | { kind: "votes"; subject: string; revote: boolean; votes: { agent: string; stance: string; confidence: number; condition: string | null }[]; compromise?: string }
  | { kind: "result"; subject: string; outcome: string; agreement: number | null; v: number | null; e: number | null; guardrail: string | null; reason: string }
  | { kind: "statement"; text: string; agreement: number | null }
  | { kind: "signed"; decision: string; reason: string }
  | { kind: "error"; text: string }
  | { kind: "intro"; agent: string; name: string; role: string; specialty: string; worksOn: string; votes: boolean; models: string[] };

/** Who sits at the table, as recorded at the start of a session (agent.introduced) or read from team.json. */
export interface Intro { agent: string; name: string; role: string; specialty: string; works_on: string; votes: boolean; models: string[] }

const PROVIDER: Record<string, string> = {
  anthropic: "Anthropic", openai: "OpenAI", gemini: "Google", groq: "Groq", ollama_chat: "Ollama", ollama: "Ollama",
};
/** "anthropic/claude-sonnet-5-5" → "Claude Sonnet 5.5 from Anthropic": how a person would say it. */
export function sayModel(id: string): string {
  const at = id.indexOf("/");
  const prov = at >= 0 ? PROVIDER[id.slice(0, at)] ?? id.slice(0, at) : "";
  let m = (at >= 0 ? id.slice(at + 1) : id).replace(/^.*\//, "");
  const claude = /^claude-([a-z]+)-(\d+)-(\d+)$/.exec(m);
  if (claude) m = `Claude ${claude[1][0].toUpperCase()}${claude[1].slice(1)} ${claude[2]}.${claude[3]}`;
  else if (/^gpt-/.test(m)) m = "GPT-" + m.slice(4).replace(/-/g, " ");
  else m = m.replace(/:/g, " ").replace(/(\d)b$/i, "$1B").replace(/-/g, " ").replace(/\b([a-z])/g, (c) => c.toUpperCase())
            .replace(/^([A-Za-z]+)(\d)/, "$1 $2");
  return prov ? `${m} from ${prov}` : m;
}

const TITLE: Record<string, string> = {
  moderator: "the chair of this council", strategist: "the strategist", architect: "the architect",
  platform_cost: "the platform and cost expert", critic: "the critic", fact_checker: "the fact checker",
};
function introText(x: Intro): string {
  const [main, ...backups] = x.models;
  const llm = main ? ` I run on ${sayModel(main)}${backups.length ? `, with ${sayModel(backups[0])} as my backup` : ""}.` : "";
  const rounds = x.works_on.replace(/\bR(\d)\b/g, "round $1");          // spoken: "round 4", not "R4"
  return `I'm ${x.name}, ${TITLE[x.agent] ?? x.role}. I specialise in ${x.specialty.charAt(0).toLowerCase()}${x.specialty.slice(1).replace(/\.$/, "")}. ` +
         `I work on ${rounds}.${x.votes ? " I have a vote." : " I don't vote."}${llm}`;
}

export interface Line {
  key: string;          // stable id (first event seq), so live updates do not reshuffle the transcript
  upTo: number;         // number of events this line has consumed: lets the board view sync to it
  round: Round;
  speaker: Speaker;
  text: string;         // what is said (and spoken)
  card?: TableCard;
  to?: string;          // who is addressed, for "Tara → Ada"
  topic?: string;       // the subject under discussion (framework id, build_approach, delivery_path)
  thoughts?: Partial<Record<Speaker, string>>;   // thought clouds shown with this turn
  ownThought?: boolean; // the speaker's cloud is the agent's own note (not derived from its facts)
  pages?: number[];     // document sections this turn cites, for the document panel
  quote?: string | null;
}

const NAME: Record<string, string> = {
  moderator: "Mira", strategist: "Tara", architect: "Ada", platform_cost: "Kabir", critic: "Rex", fact_checker: "Vera", you: "You",
};
const STANCE_WORDS: Record<string, string> = { adopt: "adopt", adopt_with_condition: "adopt, with a condition", reject: "reject" };
const OUTCOME_WORDS: Record<string, string> = {
  selected: "selected", selected_with_condition: "selected with a condition", reviewer_decides: "left to the reviewer",
  rejected: "rejected", parked: "parked until a fact is confirmed",
};
const TYPE_WORDS: Record<string, string> = {
  fact: "you have a fact wrong", relevance: "those facts don't lead there", evidence: "the evidence is weak",
  cost: "this costs more than you say", alternative: "there's a better option",
};
const VERDICT_WORDS: Record<string, string> = { verified: "verified", partly_supports: "partly supports", unverified: "unverified", contradicted: "contradicted" };

const pretty = (key: string) => key.replace(/_/g, " ");
const show = (v: unknown) => (typeof v === "boolean" ? (v ? "yes" : "no") : String(v));
const list = (xs: string[]) => (xs.length <= 1 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

const ROUND_SPOKEN: Record<string, string> = {
  R2: "Round two, proposals", R3: "Round three, fact check", R4: "Round four, challenges", R5: "Round five, rebuttals",
  R6: "Round six, the vote", R7: "Round seven, converging",
};

export function buildScript(log: CouncilEvent[], names: Record<string, string>, decision: Decision | null,
                            team: Intro[] = []): Line[] {
  const nm = (s: string) => names[s] ?? pretty(s);
  const lines: Line[] = [];
  const cardsBy: Record<string, { agent: string; subject: string }> = {};
  const facts: Record<string, { key: string; value: unknown; page: number | null; quote: string | null; status: string }> = {};
  const announced = log.some((e) => e.type === "round.started");   // newer runs announce their rounds
  // What an agent has in front of it, when it left no note of its own (older runs).
  const derived = (ids: string[]) => {
    const fs = ids.map((id) => facts[id]).filter(Boolean);
    return fs.length
      ? `Looking at ${fs.slice(0, 3).map((f) => `${pretty(f.key)}: ${show(f.value)}`).join("; ")}…`
      : "Nothing verified to stand on…";
  };
  const pagesOf = (ids: string[]) =>
    [...new Set(ids.map((id) => facts[id]?.page).filter((x): x is number => typeof x === "number"))];
  const think = (agent: string, own: unknown, ids: string[]) => {
    const mine = typeof own === "string" && own.trim() !== "";
    return { thoughts: { [agent]: mine ? (own as string) : derived(ids) } as Line["thoughts"], ownThought: mine, pages: pagesOf(ids) };
  };
  let i = 0;
  // After the introductions: Mira names your seat, then hands over to the fact sheet.
  const youLine = (upTo: number, key: string) => lines.push({ key: `${key}-you`, round: "R0", upTo, speaker: "moderator",
    text: "And at the table with us is you, the reviewer. You can raise your hand at any time, and at the end you approve our position or override it." });
  const facts0 = (upTo: number, key: string) => lines.push({ key: `${key}-facts`, round: "R0", upTo, speaker: "moderator",
    text: "First I read out the facts the document states; code checks every quote against the document." });
  const push = (e: CouncilEvent, l: Omit<Line, "key" | "round" | "upTo">, upTo: number) =>
    lines.push({ key: `e${e.seq}`, round: roundOf(e), upTo, ...l });

  while (i < log.length) {
    const e = log[i];
    const p = e.payload;
    switch (e.type) {
      case "session.started": {
        // Older sessions recorded no introductions: introduce the team from team.json instead.
        const recorded = log.some((x) => x.type === "agent.introduced");
        const intros = recorded ? [] : team;
        push(e, { speaker: "moderator", text: `Welcome to the council. Today we review ${p.document}, ${p.pages} sections.` +
          (recorded || intros.length ? " Before we start, each of us says who we are and what we do." : "") }, i + 1);
        intros.forEach((x) => lines.push({ key: `intro-${x.agent}`, round: "R0", upTo: i + 1, speaker: x.agent as Speaker,
          text: introText(x), card: { kind: "intro", agent: x.agent, name: x.name, role: x.role, specialty: x.specialty,
                                      worksOn: x.works_on, votes: x.votes, models: x.models } }));
        if (intros.length) youLine(i + 1, `e${e.seq}`);
        if (!recorded) facts0(i + 1, `e${e.seq}`);
        break;
      }
      case "agent.introduced": {
        const x = p as unknown as Intro;
        push(e, { speaker: x.agent as Speaker, text: introText(x), card: { kind: "intro", agent: x.agent, name: x.name, role: x.role,
          specialty: x.specialty, worksOn: x.works_on, votes: x.votes, models: x.models } }, i + 1);
        if (log[i + 1]?.type !== "agent.introduced") { youLine(i + 1, `e${e.seq}`); facts0(i + 1, `e${e.seq}`); }
        break;
      }
      case "round.started": {
        // Mira announces each debate round; the agents named are shown thinking (R0 and R1 are already introduced).
        if (p.round !== "R0" && p.round !== "R1") {
          const who = (p.agents as string[]).filter((a) => a !== "moderator");
          const text = who.length
            ? `${ROUND_SPOKEN[p.round] ?? p.round}. ${p.doing}. ${list(who.map((a) => NAME[a] ?? a))}, over to you.`
            : `${p.doing}.`;
          push(e, { speaker: "moderator", text,
                    thoughts: Object.fromEntries((p.agents as string[]).map((a) => [a, `${p.doing}…`])) }, i + 1);
        }
        break;
      }
      case "fact.extracted": {
        facts[p.id] = { key: p.key, value: p.value, page: p.page, quote: p.quote, status: p.status };
        const said = p.status === "confirmed"
          ? `${pretty(p.key)}: ${show(p.value)}. Page ${p.page} says so.`
          : `${pretty(p.key)}: ${show(p.value)}. The document doesn't say; that's an assumption.`;
        push(e, { speaker: "moderator", text: said, pages: p.page ? [p.page] : [], quote: p.quote, card: { kind: "fact", id: p.id, label: pretty(p.key), value: show(p.value), status: p.status, quote: p.quote, page: p.page, note: p.note } }, i + 1);
        break;
      }
      case "factsheet.ready": {
        const c = p.counts ?? {};
        push(e, { speaker: "moderator", text: `That's the fact sheet: ${c.confirmed ?? 0} confirmed facts and ${c.assumed ?? 0} assumptions. Tara, which frameworks apply?` }, i + 1);
        break;
      }
      case "shortlist.ready": {
        const items = p.items as { id: string; name: string; status: string; reason: string }[];
        const by = (s: string) => items.filter((x) => x.status === s).map((x) => x.name);
        const parts = [
          by("binding").length ? `${list(by("binding"))} ${by("binding").length > 1 ? "are" : "is"} binding: the facts require ${by("binding").length > 1 ? "them" : "it"}.` : "",
          by("candidate").length ? `Up for debate: ${list(by("candidate"))}.` : "",
          by("needs_fact").length ? `We can't judge ${list(by("needs_fact"))} without more facts.` : "",
          by("not_applicable").length ? `Not applicable: ${list(by("not_applicable"))}.` : "",
        ].filter(Boolean);
        push(e, { speaker: "strategist", text: `I matched every framework's rules against the facts. ${parts.join(" ")} Now each of us writes our position, without seeing the others.`, card: { kind: "shortlist", items } }, i + 1);
        break;
      }
      case "card.proposed": {
        cardsBy[p.id] = { agent: p.agent, subject: p.subject };
        const cond = p.stance === "adopt_with_condition" && p.condition ? ` My condition: ${p.condition}` : "";
        push(e, {
          speaker: p.agent, topic: p.subject, ...think(p.agent, p.thinking, p.facts ?? []),
          text: `On ${nm(p.subject)}, I say ${STANCE_WORDS[p.stance] ?? p.stance}. ${p.claim}${cond}`,
          card: { kind: "argument", agent: p.agent, subject: p.subject, stance: p.stance, claim: p.claim, facts: p.facts ?? [], condition: p.condition, issues: p.issues ?? [] },
        }, i + 1);
        break;
      }
      case "factcheck.verdict": {
        // R3 verdicts on cards: Vera reports once per subject. Verdicts on challenges and rebuttals are
        // already folded into their weights, so they are not read out.
        const start = i;
        const block: CouncilEvent[] = [];
        while (i < log.length && log[i].type === "factcheck.verdict") block.push(log[i++]);
        const onCards = block.filter((v) => cardsBy[v.payload.card]);
        const subjects = [...new Set(onCards.map((v) => cardsBy[v.payload.card].subject))];
        subjects.forEach((s, n) => {
          const mine = onCards.filter((v) => cardsBy[v.payload.card].subject === s);
          const ids = [...new Set(mine.map((v) => v.payload.card as string))];
          const rows = ids.map((id) => {
            const vs = mine.filter((v) => v.payload.card === id);
            return { agent: cardsBy[id].agent, weight: vs.reduce((a, v) => a + (v.payload.weight ?? 0), 0),
                     marks: vs.map((v) => ({ ref: v.payload.ref, verdict: v.payload.verdict, note: v.payload.note })) };
          });
          const strong = rows.filter((r) => r.weight > 0).map((r) => NAME[r.agent]);
          const weak = rows.filter((r) => r.weight === 0).map((r) => NAME[r.agent]);
          const notRelevant = mine.filter((v) => v.payload.by === "judge" && v.payload.verdict !== "verified");
          const bad = mine.filter((v) => v.payload.verdict === "contradicted");
          const text = [
            `${nm(s)}.`,
            strong.length ? `${list(strong)} ${strong.length > 1 ? "stand" : "stands"} on checked facts.` : "",
            weak.length ? `${list(weak)}: nothing verified, so no weight.` : "",
            notRelevant.length ? `${notRelevant.length === 1 ? "One fact doesn't" : `${notRelevant.length} facts don't`} support what was claimed.` : "",
            bad.length ? `A fact contradicts ${list(bad.map((v) => NAME[cardsBy[v.payload.card].agent]))}; that argument is out.` : "",
          ].filter(Boolean).join(" ");
          const refs = [...new Set(mine.map((v) => v.payload.ref as string))];
          lines.push({ key: `e${mine[0].seq}`, round: "R3", upTo: start + block.indexOf(mine[mine.length - 1]) + 1,
                       speaker: "fact_checker", text, topic: s, pages: pagesOf(refs), card: { kind: "check", subject: s, rows } });
          if (n === 0 && subjects.length > 1) {
            // first subject: Vera explains what the source marks mean, once
            lines[lines.length - 1].text += " Framework sources show a question mark until we fetch their pages.";
          }
        });
        continue;                                                   // i already moved past the block
      }
      case "challenge.raised": {
        const to = p.counter_case ? "" : NAME[p.target_agent] ?? p.target_agent;
        const text = p.counter_case
          ? `Everyone agreed on ${nm(p.target_subject)}, so I'll argue the opposite. ${p.text}`
          : `${to}, on ${nm(p.target_subject)}: ${TYPE_WORDS[p.challenge_type] ?? p.challenge_type}. ${p.text}`;
        push(e, { speaker: p.agent, to: p.counter_case ? "the panel" : to, text, topic: p.target_subject,
          ...think(p.agent, p.thinking, p.facts ?? []),
          card: { kind: "challenge", agent: p.agent, target: p.counter_case ? "the panel" : to, subject: p.target_subject, type: p.challenge_type,
                  text: p.text, weight: p.weight, counter: Boolean(p.counter_case), facts: p.facts ?? [] } }, i + 1);
        break;
      }
      case "rebuttal.made": {
        const challenger = String(p.challenge).split(">")[0];
        const to = NAME[challenger] ?? challenger;
        const text = p.response === "concede" ? `${to}, you're right. ${p.text}`
          : p.response === "revise" ? `${to}, fair point. I have changed the proposal. ${p.text}` : `${to}, I disagree. ${p.text}`;
        push(e, { speaker: p.agent, to, text, topic: p.subject, ...think(p.agent, p.thinking, p.facts ?? []),
          card: { kind: "rebuttal", agent: p.agent, subject: p.subject, response: p.response, text: p.text, weight: p.weight, facts: p.facts ?? [] } }, i + 1);
        break;
      }
      case "vote.cast": {
        // A block of votes: Mira reveals them subject by subject, after everyone has voted.
        const start = i;
        const block: CouncilEvent[] = [];
        while (i < log.length && log[i].type === "vote.cast") block.push(log[i++]);
        const revote = Boolean(block[0].payload.revote);
        const subjects = [...new Set(block.map((v) => v.payload.subject as string))];
        if (revote) {
          lines.push({ key: `e${block[0].seq}-intro`, round: "R7", upTo: start, speaker: "moderator",
                       text: `We're split on ${list(subjects.map(nm))}. The rules allow one compromise and one re-vote.` });
        } else if (!announced) {
          lines.push({ key: `e${block[0].seq}-intro`, round: "R6", upTo: start, speaker: "moderator",
                       text: "Time to vote. Everyone votes at once and nobody sees the others. Here are the votes." });
        } else {
          lines.push({ key: `e${block[0].seq}-intro`, round: "R6", upTo: start, speaker: "moderator",
                       text: "The votes are in. Here they are, subject by subject." });
        }
        for (const s of subjects) {
          const vs = block.filter((v) => v.payload.subject === s).map((v) => v.payload);
          const compromise = revote ? decision?.revote?.compromises?.[s] : undefined;
          const said = vs.map((v) => `${NAME[v.agent]} ${STANCE_WORDS[v.stance] ?? v.stance}`).join("; ");
          const last = block.filter((v) => v.payload.subject === s).pop()!;
          const thoughts = Object.fromEntries(vs.map((v) => [v.agent, typeof v.thinking === "string" && v.thinking.trim()
            ? v.thinking : `${STANCE_WORDS[v.stance] ?? v.stance}, confidence ${v.confidence}. Convinced by ${v.convinced_by}.`]));
          lines.push({ key: `e${last.seq}-${s}`, round: revote ? "R7" : "R6", upTo: start + block.indexOf(last) + 1, speaker: "moderator",
                       topic: s, thoughts,
                       text: `${compromise ? `On ${nm(s)}, my compromise: ${compromise} The re-vote: ` : `${nm(s)}: `}${said}.`,
                       card: { kind: "votes", subject: s, revote, compromise,
                               votes: vs.map((v) => ({ agent: v.agent, stance: v.stance, confidence: v.confidence, condition: v.condition })) } });
        }
        continue;
      }
      case "consensus.result": {
        const a = p.agreement !== null && p.agreement !== undefined ? ` Agreement ${Math.round(p.agreement)} percent.` : "";
        const why = p.reasons?.[p.reasons.length - 1] ?? "";
        const capped = why.startsWith("Capped") ? " An objection was never answered with evidence, so it goes to the reviewer." : "";
        const guard = p.guardrail ? ` The condition: ${p.guardrail}` : "";
        push(e, { speaker: "moderator", topic: p.subject,
                  text: `${p.name ?? nm(p.subject)}: ${OUTCOME_WORDS[p.outcome] ?? p.outcome}.${a}${capped}${guard}`,
          card: { kind: "result", subject: p.subject, outcome: p.outcome, agreement: p.agreement, v: p.vote_support, e: p.evidence_balance,
                  guardrail: p.guardrail, reason: why } }, i + 1);
        break;
      }
      case "stage.decided":
        push(e, { speaker: "moderator", text: `Here is the position the panel signs. ${p.statement}`,
                  card: { kind: "statement", text: p.statement, agreement: p.stage_agreement } }, i + 1);
        break;
      case "reviewer.signed": {
        const d = p.decision === "approve" ? "approved" : "overrode";
        push(e, { speaker: p.by === "room" ? "you" : "moderator",
                  text: p.by === "room" ? (p.decision === "approve" ? "I approve this strategy." : `I override: ${p.reason}`)
                                        : `The reviewer ${d}${p.reason ? `: ${p.reason}` : ""}.`,
                  card: { kind: "signed", decision: p.decision, reason: p.reason } }, i + 1);
        break;
      }
      case "error":
        push(e, { speaker: "moderator", text: `${NAME[p.agent] ?? p.agent} didn't answer in ${p.round}; we go on without that turn.`,
                  card: { kind: "error", text: String(p.error).slice(0, 240) } }, i + 1);
        break;
    }
    i++;
  }
  return lines;
}
