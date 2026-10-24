"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { CouncilEvent } from "@/lib/types";
import { useStored } from "@/lib/useStored";
import {
  AGENTS, dwell, OUTCOME_LABEL, ROUND_TITLES, ROUNDS, roundEnds, roundOf, snapshot, STANCE_SHORT, VERDICT_MARK,
  VOTERS, type Card, type Round, type Snapshot,
} from "@/lib/replay";

const SPEEDS = [1, 2, 4, 8];
const SECTION_OF: Record<Round, string> = {
  R0: "facts", R1: "shortlist", R2: "debate", R3: "debate", R4: "debate", R5: "debate", R6: "vote", R7: "decision", Gate: "decision",
};

function Agent({ id }: { id: string }) {
  const a = AGENTS[id];
  if (!a) return <span className="agent">{id}</span>;
  return (
    <span className="agent" title={a.role}>
      <span className="dot" style={{ background: a.color }} />
      {a.name}
    </span>
  );
}

// `start`: where the replay opens, from ?at=end or ?at=<event number> in the URL (`fromUrl`);
// without one, coming back resumes where you left it.
export default function Replay({ id, log, names, start = 0, fromUrl = false }: {
  id: string; log: CouncilEvent[]; names: Record<string, string>; start?: number; fromUrl?: boolean;
}) {
  const [stored, setPos] = useStored(`board:${id}:pos`, start, fromUrl);
  const pos = Math.min(stored, log.length);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useStored("board:speed", 2);
  const snap = useMemo(() => snapshot(log, pos), [log, pos]);
  const ends = useMemo(() => roundEnds(log), [log]);
  const lastRound = useRef<string>("");

  // Playback: each event stays on screen for its dwell time, divided by the speed.
  useEffect(() => {
    if (!playing) return;
    if (pos >= log.length) { setPlaying(false); return; }
    const t = setTimeout(() => setPos((p) => Math.min(p + 1, log.length)), dwell(log[pos]) / speed);
    return () => clearTimeout(t);
  }, [playing, pos, speed, log]);

  // Follow the debate: when a new round starts, bring its section into view.
  useEffect(() => {
    if (!playing || pos === 0) return;
    const section = SECTION_OF[snap.round];
    if (section !== lastRound.current) {
      lastRound.current = section;
      document.getElementById(section)?.scrollIntoView({ block: "start" });
    }
  }, [snap.round, playing, pos]);

  const current = pos > 0 ? roundOf(log[pos - 1]) : null;
  const name = (s: string) => names[s] ?? s;

  return (
    <>
      <div className="controls">
        <div className="row">
          <button className="primary" onClick={() => { if (pos >= log.length) setPos(0); setPlaying(!playing); }}>
            {playing ? "❚❚ Pause" : pos >= log.length ? "↺ Replay" : "▶ Play"}
          </button>
          <button onClick={() => { setPlaying(false); setPos((p) => Math.max(0, p - 1)); }} aria-label="Step back">◀</button>
          <button onClick={() => { setPlaying(false); setPos((p) => Math.min(log.length, p + 1)); }} aria-label="Step forward">▶</button>
          <button onClick={() => { setPlaying(false); setPos(log.length); }}>Show final</button>
          <span className="muted" style={{ marginLeft: 6 }}>Speed</span>
          {SPEEDS.map((s) => (
            <button key={s} className={s === speed ? "on" : ""} onClick={() => setSpeed(s)}>{s}×</button>
          ))}
          <input type="range" min={0} max={log.length} value={pos} aria-label="Position in the run"
                 onChange={(e) => { setPlaying(false); setPos(Number(e.target.value)); }} />
          <span className="mono muted">{pos}/{log.length}</span>
        </div>
        <div className="steps">
          {ROUNDS.map((r) => {
            const end = ends[r];
            const state = current === r ? "current" : end !== undefined && pos >= end ? "done" : "todo";
            return (
              <button key={r} className={`step ${state}`} disabled={end === undefined}
                      onClick={() => { setPlaying(false); if (end !== undefined) setPos(end); }}>
                {r} · {ROUND_TITLES[r]}
              </button>
            );
          })}
        </div>
      </div>

      <div className="layout">
        <div>
          <Facts snap={snap} current={SECTION_OF[snap.round] === "facts" && pos > 0} />
          <Shortlist snap={snap} current={SECTION_OF[snap.round] === "shortlist"} />
          <Debate snap={snap} name={name} current={SECTION_OF[snap.round] === "debate"} />
          <Vote snap={snap} name={name} current={SECTION_OF[snap.round] === "vote"} />
          <DecisionView snap={snap} name={name} current={SECTION_OF[snap.round] === "decision"} />
        </div>
        <Rail log={log} pos={pos} name={name} />
      </div>
    </>
  );
}

/* ---------- R0 · fact sheet ---------- */
function Facts({ snap, current }: { snap: Snapshot; current: boolean }) {
  const status = (s: string) => (s === "confirmed" ? "good" : s === "assumed" ? "warn" : "bad");
  return (
    <section id="facts" className={`panel section ${current ? "current" : ""}`}>
      <header><span className="tag">R0</span><h2>Fact sheet</h2><span className="muted">{snap.document}</span></header>
      {snap.facts.length === 0 ? <p className="empty">Mira reads the PRD and extracts facts; code checks every quote.</p> : (
        <table className="facts">
          <thead><tr><th>id</th><th>fact</th><th>value</th><th>status</th><th>page</th><th>quote from the PRD</th></tr></thead>
          <tbody>
            {snap.facts.map((f) => (
              <tr key={f.id}>
                <td className="mono">{f.id}</td><td>{f.key}</td><td className="mono">{JSON.stringify(f.value)}</td>
                <td><span className={`chip ${status(f.status)}`}>{f.status}</span></td>
                <td>{f.page ?? ""}</td>
                <td className="quote">{f.quote ? `“${f.quote}”` : f.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

/* ---------- R1 · shortlist ---------- */
function Shortlist({ snap, current }: { snap: Snapshot; current: boolean }) {
  const cls: Record<string, string> = { binding: "accent", candidate: "good", needs_fact: "warn", not_applicable: "na" };
  return (
    <section id="shortlist" className={`panel section ${current ? "current" : ""}`}>
      <header><span className="tag">R1</span><h2>Shortlist</h2><span className="muted">framework rules matched against the facts, in code</span></header>
      {snap.shortlist.length === 0 ? <p className="empty">Waiting for the fact sheet.</p> : (
        <div className="shortlist">
          {snap.shortlist.map((i) => (
            <span key={i.id} className={`chip ${cls[i.status] ?? ""}`} title={i.reason}>
              {i.name} · {i.status.replace("_", " ")}{i.depends_on_assumption ? " · assumption" : ""}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

/* ---------- R2–R5 · cards, verdicts, challenges, rebuttals ---------- */
function Debate({ snap, name, current }: { snap: Snapshot; name: (s: string) => string; current: boolean }) {
  const subjects = [...new Set(snap.cards.map((c) => c.subject))];
  return (
    <section id="debate" className={`panel section ${current ? "current" : ""}`}>
      <header>
        <span className="tag">R2–R5</span><h2>Debate</h2>
        <span className="muted">blind proposals · fact-check stamps · challenges · rebuttals</span>
      </header>
      {subjects.length === 0 ? <p className="empty">The four voters write their argument cards blind, in parallel.</p> :
        subjects.map((s) => <Subject key={s} subject={s} snap={snap} name={name} />)}
    </section>
  );
}

function Subject({ subject, snap, name }: { subject: string; snap: Snapshot; name: (s: string) => string }) {
  const cards = snap.cards.filter((c) => c.subject === subject);
  const chs = snap.challenges.filter((c) => c.target_subject === subject);
  const status = snap.shortlist.find((i) => i.id === subject)?.status;
  return (
    <div className="subject">
      <div className="head">
        <h3>{name(subject)}</h3>
        {status === "binding" && <span className="chip accent">binding</span>}
        <span className="mono muted">{subject}</span>
      </div>
      <div className="cards">
        {VOTERS.map((a) => {
          const c = cards.find((x) => x.agent === a);
          return c ? <CardView key={a} card={c} snap={snap} /> : (
            <div key={a} className="card slot"><Agent id={a} /> <span>no card</span></div>
          );
        })}
      </div>
      {chs.length > 0 && (
        <div className="exchange">
          {chs.map((ch) => {
            const r = snap.rebuttals.find((x) => x.challenge === ch.id);
            const answered = r && r.response === "rebut" && (r.weight ?? 0) > 0;
            return (
              <div key={ch.id}>
                <div className={`challenge ${ch.counter_case ? "counter" : ""}`}>
                  <div className="who-line">
                    <Agent id={ch.agent} />
                    <span>{ch.counter_case ? "counter-case to the panel" : <>challenges <Agent id={ch.target_agent} /></>}</span>
                    <span className="chip bad">{ch.challenge_type}</span>
                    <span className="mono">w {ch.weight ?? "…"}</span>
                    {r && <span className={`chip ${r.response === "concede" ? "" : answered ? "good" : "warn"}`}>
                      {r.response === "concede" ? "conceded" : answered ? "answered" : "open"}</span>}
                  </div>
                  {ch.text}
                </div>
                {r && (
                  <div className={`rebuttal ${r.response}`}>
                    <div className="who-line"><Agent id={r.agent} /><span>{r.response === "concede" ? "concedes" : "rebuts"}</span>
                      {r.weight !== null && <span className="mono">w {r.weight}</span>}</div>
                    {r.text}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function CardView({ card, snap }: { card: Card; snap: Snapshot }) {
  const checks = snap.checks.filter((k) => k.card === card.id);
  const withdrawn = card.removed || card.conceded;
  return (
    <div className={`card ${withdrawn ? "withdrawn" : ""}`} style={{ ["--who" as string]: AGENTS[card.agent]?.color }}>
      <div className="top">
        <Agent id={card.agent} />
        <span className={`stance ${card.stance}`}>{STANCE_SHORT[card.stance]}</span>
      </div>
      <div className="claim" title={card.claim}>{card.claim}</div>
      {card.condition && <div className="guardrail">if: {card.condition}</div>}
      <div className="foot">
        {checks.length > 0
          ? checks.map((k) => <span key={k.ref} className={`v-${k.verdict}`} title={k.note ?? k.verdict}>{k.ref}{VERDICT_MARK[k.verdict]}</span>)
          : card.facts.map((f) => <span key={f}>{f}</span>)}
        {card.weight !== null && <span>· w {card.weight}</span>}
        {card.conceded && <span className="chip">conceded</span>}
        {card.removed && <span className="chip bad">contradicted</span>}
        {card.issues.length > 0 && <span className="chip warn" title={card.issues.join("; ")}>{card.issues.length} issue</span>}
      </div>
    </div>
  );
}

/* ---------- R6 · blind vote (and R7 re-vote) ---------- */
function Vote({ snap, name, current }: { snap: Snapshot; name: (s: string) => string; current: boolean }) {
  const subjects = [...new Set(snap.votes.map((v) => v.subject))];
  return (
    <section id="vote" className={`panel section ${current ? "current" : ""}`}>
      <header><span className="tag">R6</span><h2>Blind vote</h2><span className="muted">stance / confidence 1–5 · re-votes from R7 marked ↻</span></header>
      {subjects.length === 0 ? <p className="empty">Voters vote on every open subject at the same time; nobody sees another vote.</p> : (
        <div className="votes">
          {subjects.map((s) => {
            const result = snap.results.find((r) => r.subject === s);
            return (
              <div key={s} className="vote-row">
                <div><strong>{name(s)}</strong></div>
                <div className="vchips">
                  {VOTERS.map((a) => {
                    const v = snap.votes.find((x) => x.agent === a && x.subject === s);
                    const rv = snap.revotes.find((x) => x.agent === a && x.subject === s);
                    if (!v && !rv) return null;
                    const final = rv ?? v!;
                    return (
                      <span key={a} className="vchip" style={{ ["--who" as string]: AGENTS[a]?.color }}
                            title={`${AGENTS[a]?.name}: convinced by ${final.convinced_by}${final.condition ? ` · if: ${final.condition}` : ""}`}>
                        {rv && v && rv.stance !== v.stance && <span className="old">{STANCE_SHORT[v.stance]}</span>}
                        <span className={`stance ${final.stance}`}>{STANCE_SHORT[final.stance]}</span>/{final.confidence}{rv ? " ↻" : ""}
                      </span>
                    );
                  })}
                </div>
                <Meter result={result} />
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function Meter({ result }: { result?: Snapshot["results"][number] }) {
  if (!result) return <div className="muted" style={{ fontSize: 12 }}>agreement after R7</div>;
  const a = result.agreement ?? 0;
  const fill = a >= 60 ? "var(--good)" : a >= 40 ? "var(--warn)" : "var(--bad)";
  return (
    <div>
      <div className="meter" style={{ ["--fill" as string]: fill }}>
        <span style={{ width: `${result.agreement ?? 0}%` }} />
        {[40, 60, 75].map((t) => <i key={t} className="tick" style={{ left: `${t}%` }} />)}
      </div>
      <div style={{ fontSize: 12, marginTop: 3 }}>
        <span className={`outcome o-${result.outcome}`}>{OUTCOME_LABEL[result.outcome] ?? result.outcome}</span>
        {result.agreement !== null && <span className="mono"> · A {Math.round(result.agreement)}%</span>}
      </div>
    </div>
  );
}

/* ---------- R7 · decision ---------- */
function DecisionView({ snap, name, current }: { snap: Snapshot; name: (s: string) => string; current: boolean }) {
  return (
    <section id="decision" className={`panel section ${current ? "current" : ""}`}>
      <header><span className="tag">R7</span><h2>Decision</h2><span className="muted">V vote · E evidence · A = 0.6·V + 0.4·E, computed by code</span></header>
      {snap.results.length === 0 ? <p className="empty">The consensus engine turns votes and surviving evidence into an agreement % per subject.</p> : (
        <>
          <table>
            <thead><tr><th>subject</th><th>V</th><th>E</th><th>A</th><th>outcome</th><th>guardrail or reason</th></tr></thead>
            <tbody>
              {snap.results.map((r) => (
                <tr key={r.subject}>
                  <td>{r.name ?? name(r.subject)}{r.revoted ? " ↻" : ""}</td>
                  <td className="mono">{r.vote_support ?? ""}</td>
                  <td className="mono">{r.evidence_balance ?? ""}</td>
                  <td className="mono"><strong>{r.agreement ?? ""}</strong></td>
                  <td className={`outcome o-${r.outcome}`}>{OUTCOME_LABEL[r.outcome] ?? r.outcome}</td>
                  <td style={{ fontSize: 13 }}>{r.guardrail ?? r.reasons[r.reasons.length - 1]}
                    {r.flags.map((f) => <div key={f} className="chip warn" style={{ marginTop: 4 }}>{f}</div>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {snap.statement && (
            <div style={{ marginTop: 16, display: "grid", gridTemplateColumns: "auto 1fr", gap: 18, alignItems: "start" }}>
              <div>
                <div className="big">{snap.stageAgreement !== null ? `${Math.round(snap.stageAgreement)}%` : "—"}</div>
                <div className="muted" style={{ fontSize: 12 }}>stage agreement</div>
              </div>
              <div>
                <h3 style={{ marginBottom: 6 }}>Position statement</h3>
                <p className="statement">{snap.statement}</p>
              </div>
            </div>
          )}
          {snap.signed && (
            <p style={{ marginTop: 12 }}>
              <span className={`chip ${snap.signed.decision === "approve" ? "good" : "warn"}`}>Reviewer: {snap.signed.decision}</span>{" "}
              <span className="muted">{snap.signed.reason}</span>
            </p>
          )}
        </>
      )}
    </section>
  );
}

/* ---------- evidence rail: the newest events as pop-up cards ---------- */
function Rail({ log, pos, name }: { log: CouncilEvent[]; pos: number; name: (s: string) => string }) {
  const recent = log.slice(Math.max(0, pos - 40), pos).filter((e) => e.type !== "factcheck.verdict" || e.payload.by === "judge")
    .slice(-8).reverse();
  return (
    <aside className="rail" aria-label="Evidence as it arrives">
      {recent.length === 0 && <div className="panel muted">Press play. Evidence slides in here as each agent speaks.</div>}
      {recent.map((e) => <Pop key={e.seq} e={e} name={name} />)}
    </aside>
  );
}

function Pop({ e, name }: { e: CouncilEvent; name: (s: string) => string }) {
  const p = e.payload;
  const who = (id: string) => ({ ["--who" as string]: AGENTS[id]?.color });
  switch (e.type) {
    case "fact.extracted":
      return (
        <div className="pop" style={who("moderator")}>
          <div className="kind">Fact · {p.id}</div>
          <span className={`stamp ${p.status === "confirmed" ? "v-verified" : "v-partly_supports"}`}>{p.status}</span>
          <strong>{p.key}</strong> = <span className="mono">{JSON.stringify(p.value)}</span>
          {p.quote && <div className="muted">“{p.quote}” · p.{p.page}</div>}
        </div>
      );
    case "card.proposed":
      return (
        <div className="pop" style={who(p.agent)}>
          <div className="kind">Argument · {name(p.subject)}</div>
          <Agent id={p.agent} /> <span className={`stance ${p.stance}`}>{STANCE_SHORT[p.stance as keyof typeof STANCE_SHORT]}</span>
          <div>{p.claim}</div>
        </div>
      );
    case "factcheck.verdict":
      return (
        <div className="pop" style={who("fact_checker")}>
          <div className="kind">Fact check · {p.ref}</div>
          <span className={`stamp v-${p.verdict}`}>{String(p.verdict).replace("_", " ")}</span>
          <div className="mono muted">{p.card}</div>
          <div>{p.note}</div>
        </div>
      );
    case "challenge.raised":
      return (
        <div className="pop" style={who(p.agent)}>
          <div className="kind">Challenge · {p.challenge_type}{p.counter_case ? " · counter-case" : ""}</div>
          <Agent id={p.agent} /> → {p.counter_case ? "panel" : <Agent id={p.target_agent} />} on {name(p.target_subject)}
          <div>{p.text}</div>
        </div>
      );
    case "rebuttal.made":
      return (
        <div className="pop" style={who(p.agent)}>
          <div className="kind">{p.response === "concede" ? "Concession" : "Rebuttal"} · {name(p.subject)}</div>
          <Agent id={p.agent} /><div>{p.text}</div>
        </div>
      );
    case "vote.cast":
      return (
        <div className="pop" style={who(p.agent)}>
          <div className="kind">{p.revote ? "Re-vote" : "Vote"} · {name(p.subject)}</div>
          <Agent id={p.agent} /> <span className={`stance ${p.stance}`}>{STANCE_SHORT[p.stance as keyof typeof STANCE_SHORT]}</span> · confidence {p.confidence}
        </div>
      );
    case "consensus.result":
      return (
        <div className="pop">
          <div className="kind">Result · {p.name ?? name(p.subject)}</div>
          <span className={`stamp o-${p.outcome}`}>{OUTCOME_LABEL[p.outcome] ?? p.outcome}</span>
          <div className="mono">{p.agreement !== null ? `A ${Math.round(p.agreement)}%` : "no %"}</div>
        </div>
      );
    case "stage.decided":
      return <div className="pop"><div className="kind">Stage decided</div><div className="big">{p.stage_agreement !== null ? `${Math.round(p.stage_agreement)}%` : "—"}</div></div>;
    case "reviewer.signed":
      return <div className="pop" style={who("moderator")}><div className="kind">Reviewer</div>{p.decision} <span className="muted">{p.reason}</span></div>;
    case "error":
      return <div className="pop" style={{ ["--who" as string]: "var(--bad)" }}><div className="kind">Error · {p.round}</div>{p.agent}: {String(p.error).slice(0, 160)}</div>;
    default:
      return <div className="pop"><div className="kind">{e.type}</div></div>;
  }
}
