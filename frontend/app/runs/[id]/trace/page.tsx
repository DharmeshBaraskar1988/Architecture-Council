import Link from "next/link";
import { notFound } from "next/navigation";
import { loadTeam, splitModel, type Team } from "@/lib/team";
import { authorOf, finalVotes, loadTrace, type Trace } from "@/lib/trace";
import s from "./trace.module.css";

export const dynamic = "force-dynamic";

const WHO: Record<string, { name: string; role: string; color: string }> = {
  moderator: { name: "Mira", role: "Moderator", color: "var(--c-mod)" },
  strategist: { name: "Tara", role: "Strategist", color: "var(--c-str)" },
  architect: { name: "Ada", role: "Architect", color: "var(--c-arch)" },
  platform_cost: { name: "Kabir", role: "Platform & Cost", color: "var(--c-cloud)" },
  critic: { name: "Rex", role: "Critic", color: "var(--c-critic)" },
  fact_checker: { name: "Vera", role: "Fact checker", color: "var(--c-fact)" },
  you: { name: "You", role: "Reviewer", color: "var(--accent)" },
  code: { name: "Code", role: "Consensus engine", color: "var(--ink)" },
};
const VOTERS = ["strategist", "architect", "platform_cost", "critic"];
const STANCE: Record<string, string> = { adopt: "adopt", adopt_with_condition: "adopt with condition", reject: "reject" };
const OUTCOME: Record<string, string> = {
  selected: "Selected", selected_with_condition: "Selected with condition", reviewer_decides: "Reviewer decides",
  rejected: "Rejected", parked: "Parked", not_applicable: "Not applicable",
};
const MARK: Record<string, string> = { verified: "✓", partly_supports: "½", unverified: "?", contradicted: "✗" };

function Who({ id, small }: { id: string; small?: boolean }) {
  const w = WHO[id] ?? { name: id, role: "", color: "var(--muted)" };
  return (
    <span className={small ? s.whoSmall : s.who} title={w.role}>
      <span className={s.dot} style={{ background: w.color }} />{w.name}
    </span>
  );
}
const pct = (x: number | null | undefined) => (x === null || x === undefined ? "—" : `${Math.round(x)}%`);
const show = (v: unknown) => (typeof v === "boolean" ? (v ? "yes" : "no") : String(v));

export default async function TracePage({ params, searchParams }: {
  params: Promise<{ id: string }>; searchParams: Promise<{ s?: string }>;
}) {
  const { id } = await params;
  const { s: picked } = await searchParams;
  const [t, team] = await Promise.all([loadTrace(id), loadTeam(id)]);
  if (!t) notFound();
  const subject = picked && t.board.some((r) => r.subject === picked) ? picked : t.board[0]?.subject ?? t.cards[0]?.subject;
  const nm = (x: string) => t.names[x] ?? x;

  return (
    <main className="wrap">
      <div className="topbar">
        <Link href={`/runs/${id}/room`}>← Room</Link>
        <h1>Who is behind the decision</h1>
        <span className="muted">{t.document}</span>
        <Link href={`/runs/${id}/output`} style={{ marginLeft: "auto" }}>Final output →</Link>
      </div>
      {team && <TeamTable team={team} />}
      <Pipeline t={t} />
      <CheckedWhom t={t} />
      {subject && (
        <>
          <h2 className={s.h2}>Behind each decision</h2>
          <p className="muted" style={{ marginTop: 0 }}>Pick a subject to follow it from the facts to the result.</p>
          <nav className={s.subjects}>
            {(t.board.length ? t.board.map((r) => ({ id: r.subject, outcome: r.outcome, a: r.agreement }))
              : [...new Set(t.cards.map((c) => c.subject))].map((x) => ({ id: x, outcome: "", a: null }))).map((r) => (
              <Link key={r.id} href={`/runs/${id}/trace?s=${r.id}`} scroll={false}
                    className={`${s.subject} ${r.id === subject ? s.on : ""} ${s["o_" + r.outcome] ?? ""}`}>
                {nm(r.id)}<span>{r.outcome ? `${OUTCOME[r.outcome] ?? r.outcome}${r.a !== null ? ` · ${pct(r.a)}` : ""}` : "no result yet"}</span>
              </Link>
            ))}
          </nav>
          <SubjectTrace t={t} subject={subject} />
        </>
      )}
    </main>
  );
}

/* ---------- 0. who sat at the table, and on which LLM ---------- */
function TeamTable({ team }: { team: Team }) {
  return (
    <section className={`panel ${s.section}`}>
      <h2 className={s.h2}>Who worked on this, and on which LLM</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Each agent has a main model and backups, tried in order when a provider fails or a free quota runs out.
        {" "}{team.calls} model calls in this session · {team.failed} failed or retried · ${team.cost.toFixed(3)}
      </p>
      <div className={s.scroll}>
        <table className={s.matrix}>
          <thead><tr><th>agent</th><th>job · specialised in · works on</th><th>set to use (in order)</th><th>actually answered with</th><th>calls</th><th>time</th><th>cost</th></tr></thead>
          <tbody>
            {team.members.map((m) => {
              const ok = m.used.filter((u) => u.ok > 0);
              return (
                <tr key={m.agent}>
                  <td><Who id={m.agent} />{m.votes && <div className={s.sub}>votes</div>}</td>
                  <td style={{ minWidth: 260 }}>
                    <strong>{m.role}</strong>
                    {m.specialty && <div style={{ fontSize: 13, marginTop: 2 }}>{m.specialty}</div>}
                    {m.works_on && <div className={s.sub} style={{ marginTop: 2 }}>Works on: {m.works_on}</div>}
                  </td>
                  <td>{m.models.map((x, k) => { const sm = splitModel(x); return (
                    <div key={x} className={k === 0 ? "" : s.sub}>{k === 0 ? "" : "then "}<span className="mono">{sm.model}</span> · {sm.provider}</div>
                  ); })}</td>
                  <td>
                    {ok.length === 0 ? <span className="muted">not called</span> : ok.map((u) => { const sm = splitModel(u.model); return (
                      <div key={u.model}><strong className="mono">{sm.model}</strong> · {sm.provider} <span className={s.sub}>({u.ok} answers)</span>
                        {u.model !== m.models[0] && <span className="chip warn" style={{ marginLeft: 6 }}>fallback</span>}</div>
                    ); })}
                    {m.used.filter((u) => u.ok === 0).map((u) => (
                      <div key={u.model} className={s.sub}>tried {splitModel(u.model).model}: {u.failed} failed</div>
                    ))}
                    {m.working && <div className="chip accent">working now on {m.current ? splitModel(m.current).model : "?"}</div>}
                  </td>
                  <td className="mono">{m.used.reduce((a, u) => a + u.calls, 0)}</td>
                  <td className="mono">{Math.round(m.used.reduce((a, u) => a + u.seconds, 0))} s</td>
                  <td className="mono">${m.used.reduce((a, u) => a + u.cost, 0).toFixed(3)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/* ---------- 1. how this council reached its decisions, with this run's numbers ---------- */
function Pipeline({ t }: { t: Trace }) {
  const confirmed = t.facts.filter((f) => f.status === "confirmed").length;
  const binding = t.shortlist.filter((x) => x.status === "binding").length;
  const candidates = t.shortlist.filter((x) => x.status === "candidate").length;
  const v = (k: string) => [...t.cardChecks, ...t.challengeChecks].filter((c) => c.verdict === k).length;
  const concessions = t.rebuttals.filter((r) => r.response === "concede").length;
  const steps: { who: string[]; did: string; numbers: string; note?: string }[] = [
    { who: ["moderator"], did: "Reads the document and writes down its facts",
      numbers: `${t.facts.length} facts · ${confirmed} confirmed`, note: "Code checks every quote against the document." },
    { who: ["strategist"], did: "Matches framework rules against the facts",
      numbers: `${binding} binding · ${candidates} for debate`, note: "The rules are code; Tara presents them." },
    { who: VOTERS, did: "Each writes a position on every framework, blind",
      numbers: `${t.cards.length} argument cards`, note: "Nobody sees the others' cards." },
    { who: ["fact_checker"], did: "Checks every citation in every card and challenge",
      numbers: `${v("verified")} verified · ${v("unverified")} unverified · ${v("contradicted")} contradicted`,
      note: "Assumed facts and unfetched sources are ruled by code; Vera judges if a fact supports a claim." },
    { who: VOTERS, did: "Each card is challenged by a different agent",
      numbers: `${t.challenges.length} challenges`, note: "Never by the author, never on the same provider; the Critic argues against anything everyone agreed on." },
    { who: VOTERS, did: "Each author answers: new evidence, or concede",
      numbers: `${t.rebuttals.length - concessions} rebuttals · ${concessions} concessions`, note: "An answer counts only if Vera finds evidence in it." },
    { who: VOTERS, did: "Everyone votes at once, blind",
      numbers: `${t.votes.length} votes${t.revotes.length ? ` · ${t.revotes.length} re-votes` : ""}`, note: "Each vote names the one argument that convinced it." },
    { who: ["code"], did: "Computes agreement from votes and checked evidence",
      numbers: t.stageAgreement !== null ? `stage agreement ${pct(t.stageAgreement)}` : "not yet", note: "A = 0.6 × vote + 0.4 × evidence. No model sets a number." },
    { who: ["moderator"], did: "Writes the position statement and guardrails", numbers: `${t.board.length} decisions` },
    { who: ["you"], did: "Approve, or override with a reason",
      numbers: t.review ? (t.review.decision === "approve" ? "approved" : "overridden") : "waiting for you" },
  ];
  return (
    <section className={`panel ${s.section}`}>
      <h2 className={s.h2}>How the council decided</h2>
      <ol className={s.pipeline}>
        {steps.map((st, k) => (
          <li key={k} className={s.step}>
            <span className={s.num}>{k + 1}</span>
            <div className={s.stepWho}>{st.who.map((w) => <Who key={w} id={w} small={st.who.length > 1} />)}</div>
            <div className={s.stepDid}>{st.did}</div>
            <div className={s.stepNum}>{st.numbers}</div>
            {st.note && <div className={s.stepNote}>{st.note}</div>}
          </li>
        ))}
      </ol>
    </section>
  );
}

/* ---------- 2. who checked whose answers ---------- */
function CheckedWhom({ t }: { t: Trace }) {
  const authors = VOTERS.filter((a) => t.cards.some((c) => c.agent === a));
  const cell = (checker: string, author: string) => {
    const chs = t.challenges.filter((c) => c.agent === checker && !c.counter_case && c.target_agent === author);
    return { n: chs.length, answered: chs.filter((c) => c.answered).length,
             conceded: chs.filter((c) => t.rebuttals.some((r) => r.challenge === c.id && r.response === "concede")).length };
  };
  const vera = (author: string) => {
    const ids = new Set(t.cards.filter((c) => c.agent === author).map((c) => c.id));
    const mine = t.cardChecks.filter((c) => ids.has(c.card));
    return { n: mine.length, ok: mine.filter((c) => c.verdict === "verified").length, bad: mine.filter((c) => c.verdict === "contradicted").length };
  };
  const counters = t.challenges.filter((c) => c.counter_case);
  // Whose arguments convinced the final votes, across all subjects.
  const influence: Record<string, number> = {};
  for (const r of t.board) for (const v of finalVotes(r.subject, t)) {
    const a = authorOf(v.convinced_by, t).agent;
    if (a) influence[a] = (influence[a] ?? 0) + 1;
  }
  const totalVotes = Object.values(influence).reduce((a, b) => a + b, 0);
  return (
    <section className={`panel ${s.section}`}>
      <h2 className={s.h2}>Who checked whose answers</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Rows check, columns were checked. Every card is checked twice: by Vera (its facts) and by another agent (its reasoning).
      </p>
      <div className={s.scroll}>
        <table className={s.matrix}>
          <thead>
            <tr><th>checked by ↓ · answers of →</th>{authors.map((a) => <th key={a}><Who id={a} /></th>)}</tr>
          </thead>
          <tbody>
            <tr className={s.veraRow}>
              <td><Who id="fact_checker" /><div className={s.sub}>citations</div></td>
              {authors.map((a) => { const x = vera(a); return (
                <td key={a}><strong>{x.n}</strong> checked<div className={s.sub}>{x.ok} ✓{x.bad ? ` · ${x.bad} ✗` : ""}</div></td>
              ); })}
            </tr>
            {VOTERS.map((c) => (
              <tr key={c}>
                <td><Who id={c} /><div className={s.sub}>challenges</div></td>
                {authors.map((a) => {
                  if (a === c) return <td key={a} className={s.self}>—</td>;
                  const x = cell(c, a);
                  return (
                    <td key={a} className={x.n ? "" : s.zero}>
                      {x.n ? <><strong>{x.n}</strong> challenged<div className={s.sub}>{x.answered} answered{x.conceded ? ` · ${x.conceded} conceded` : ""}</div></> : "·"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={s.facts2}>
        {counters.length > 0 && (
          <p><Who id={counters[0].agent} /> argued against the whole panel on {counters.length} subject{counters.length > 1 ? "s" : ""} everyone
            agreed on: {counters.map((c) => t.names[c.target_subject] ?? c.target_subject).join(", ")}.</p>
        )}
        {totalVotes > 0 && (
          <p>Whose arguments convinced the votes:{" "}
            {Object.entries(influence).sort((a, b) => b[1] - a[1]).map(([a, n], k) => (
              <span key={a}>{k ? " · " : ""}<Who id={a} small /> {n} of {totalVotes}</span>
            ))}
          </p>
        )}
      </div>
    </section>
  );
}

/* ---------- 3. one subject, step by step ---------- */
function SubjectTrace({ t, subject }: { t: Trace; subject: string }) {
  const nm = (x: string) => t.names[x] ?? x;
  const cards = t.cards.filter((c) => c.subject === subject);
  const chs = t.challenges.filter((c) => c.target_subject === subject);
  const rebs = t.rebuttals.filter((r) => r.subject === subject);
  const votes = finalVotes(subject, t);
  const row = t.board.find((r) => r.subject === subject);
  const short = t.shortlist.find((x) => x.id === subject);
  const factIds = [...new Set([...(short?.facts_used ?? []), ...cards.flatMap((c) => c.facts), ...chs.flatMap((c) => c.facts), ...rebs.flatMap((r) => r.facts)])];
  const facts = factIds.map((f) => t.facts.find((x) => x.id === f)).filter((f): f is NonNullable<typeof f> => Boolean(f));
  const influence: Record<string, number> = {};
  for (const v of votes) { const a = authorOf(v.convinced_by, t).agent; if (a) influence[a] = (influence[a] ?? 0) + 1; }
  const top = Object.entries(influence).sort((a, b) => b[1] - a[1])[0];

  return (
    <section className={`panel ${s.section}`}>
      <div className={s.subjectHead}>
        <h2 className={s.h2}>{nm(subject)}</h2>
        {row && <span className={`${s.outcome} ${s["o_" + row.outcome] ?? ""}`}>{OUTCOME[row.outcome] ?? row.outcome} · {pct(row.agreement)}</span>}
        {top && <span className="muted">Most votes were convinced by <Who id={top[0]} small /> ({top[1]} of {votes.length})</span>}
      </div>

      <ol className={s.chain}>
        <li>
          <h3><span className={s.num}>1</span> The facts it rests on <span className={s.by}>from the document, by <Who id="moderator" small /></span></h3>
          {short && <p className={s.sub}>Shortlist ({short.status.replace("_", " ")}): {short.reason}</p>}
          {facts.length === 0 ? <p className="empty">No facts cited.</p> : (
            <table className={s.tbl}><tbody>
              {facts.map((f) => (
                <tr key={f.id}>
                  <td className="mono">{f.id}</td><td>{f.key.replace(/_/g, " ")}: <strong>{show(f.value)}</strong></td>
                  <td><span className={`chip ${f.status === "confirmed" ? "good" : "warn"}`}>{f.status}</span></td>
                  <td className={s.quote}>{f.quote ? <>“{f.quote}” <span className={s.sub}>section {f.page}</span></> : f.note}</td>
                </tr>
              ))}
            </tbody></table>
          )}
        </li>

        <li>
          <h3><span className={s.num}>2</span> What each agent proposed <span className={s.by}>blind · checked by <Who id="fact_checker" small /></span></h3>
          <div className={s.cards}>
            {VOTERS.map((a) => {
              const c = cards.find((x) => x.agent === a);
              if (!c) return <div key={a} className={`${s.card} ${s.empty}`}><Who id={a} /> wrote no card</div>;
              const checks = t.cardChecks.filter((k) => k.card === c.id);
              return (
                <div key={a} className={`${s.card} ${c.removed || c.conceded ? s.withdrawn : ""}`} style={{ borderTopColor: WHO[a].color }}>
                  <div className={s.cardTop}><Who id={a} /><span className={s["st_" + c.stance]}>{STANCE[c.stance]}</span></div>
                  <p>{c.claim}</p>
                  {c.thinking && <p className={s.thought}>💭 {c.thinking}</p>}
                  <div className={s.marks}>
                    {checks.map((k) => <span key={k.ref} className={s["v_" + k.verdict]} title={k.note ?? k.verdict}>{k.ref}{MARK[k.verdict]}</span>)}
                    <span>· weight {c.weight ?? 0}</span>
                  </div>
                  {c.conceded && <span className="chip">withdrawn: conceded</span>}
                  {c.removed && <span className="chip bad">removed: contradicted by a fact</span>}
                </div>
              );
            })}
          </div>
        </li>

        <li>
          <h3><span className={s.num}>3</span> Who checked whose answer <span className={s.by}>challenge → answer</span></h3>
          {chs.length === 0 ? <p className="empty">Nobody challenged this subject.</p> : (
            <div className={s.exchanges}>
              {chs.map((c) => {
                const r = rebs.find((x) => x.challenge === c.id);
                return (
                  <div key={c.id} className={s.exchange}>
                    <div className={s.challenge}>
                      <div className={s.line}>
                        <Who id={c.agent} />
                        <span>{c.counter_case ? <>argued against <strong>the whole panel</strong></> : <>checked <Who id={c.target_agent} small />’s card</>}</span>
                        <span className="chip bad">{c.type}</span><span className="mono">weight {c.weight ?? 0}</span>
                      </div>
                      <p>{c.text}</p>
                      {c.thinking && <p className={s.thought}>💭 {c.thinking}</p>}
                    </div>
                    {r ? (
                      <div className={`${s.answer} ${r.response === "concede" ? s.conceded : ""}`}>
                        <div className={s.line}>
                          <Who id={r.agent} /> {r.response === "concede" ? "conceded" : "answered"}
                          {r.response === "rebut" && <span className={`chip ${c.answered ? "good" : "warn"}`}>{c.answered ? "answered with evidence" : "no evidence: still open"}</span>}
                          {r.weight !== null && <span className="mono">weight {r.weight}</span>}
                        </div>
                        <p>{r.text}</p>
                        {r.thinking && <p className={s.thought}>💭 {r.thinking}</p>}
                      </div>
                    ) : <div className={s.answer}><span className="muted">No answer.</span></div>}
                  </div>
                );
              })}
            </div>
          )}
        </li>

        <li>
          <h3><span className={s.num}>4</span> How each agent voted, and why <span className={s.by}>blind{votes.some((v) => v.revoted) ? " · re-voted on a compromise" : ""}</span></h3>
          {votes.some((v) => v.revoted) && t.compromises[subject] && (
            <p className={s.sub}><Who id="moderator" small /> proposed: {t.compromises[subject]}</p>
          )}
          {votes.length === 0 ? <p className="empty">No votes.</p> : (
            <table className={s.tbl}><tbody>
              {votes.map((v) => {
                const src = authorOf(v.convinced_by, t);
                return (
                  <tr key={v.agent}>
                    <td><Who id={v.agent} /></td>
                    <td>
                      {v.before && v.before.stance !== v.stance && <s className="muted">{STANCE[v.before.stance]}</s>}{" "}
                      <strong className={s["st_" + v.stance]}>{STANCE[v.stance]}</strong> <span className="mono">{v.confidence}/5</span>
                      {v.condition && <div className={s.sub}>if: {v.condition}</div>}
                    </td>
                    <td>
                      convinced by {src.agent ? <Who id={src.agent} small /> : "?"}'s {src.kind}
                      {src.agent === v.agent && <span className={s.sub}> (their own)</span>}
                      {src.text && <div className={s.quote}>“{src.text}”</div>}
                      {v.thinking && <div className={s.thought}>💭 {v.thinking}</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody></table>
          )}
        </li>

        <li>
          <h3><span className={s.num}>5</span> The result <span className={s.by}>computed by <Who id="code" small />, signed by <Who id="you" small /></span></h3>
          {!row ? <p className="empty">Not decided yet.</p> : (
            <div className={s.result}>
              <div className={s.sums}>
                <div><span>Vote</span><strong>{pct(row.vote_support)}</strong></div>
                <div><span>Evidence</span><strong>{pct(row.evidence_balance)}</strong></div>
                <div><span>Agreement</span><strong>{pct(row.agreement)}</strong></div>
              </div>
              <p className={s.sub}>Agreement = 0.6 × vote + 0.4 × evidence. Vote: each voter's stance weighted by confidence. Evidence: the checked
                facts for and against, each counted once.</p>
              <p><span className={`${s.outcome} ${s["o_" + row.outcome] ?? ""}`}>{OUTCOME[row.outcome] ?? row.outcome}</span>{" "}
                {row.reasons[row.reasons.length - 1]}</p>
              {row.guardrail && <p>Condition, written by <Who id="moderator" small />: {row.guardrail}</p>}
              {row.flags.map((f) => <p key={f} className="chip warn">{f}</p>)}
              <p className={s.sub}>Reviewer: {t.review ? `${t.review.decision}${t.review.reason ? `: ${t.review.reason}` : ""}` : "not signed yet"}</p>
            </div>
          )}
        </li>
      </ol>
    </section>
  );
}
