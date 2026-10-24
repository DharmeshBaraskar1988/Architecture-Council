// A small renderer for the Markdown the council writes itself (strategy_adr.md): headings, paragraphs,
// tables, bullet lists one level deep, **bold** and _italic_. React escapes all text, so nothing in the
// document can inject HTML.
import type { ReactNode } from "react";

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\*\*(.+?)\*\*|_(.+?)_/g;
  let pos = 0;
  let m: RegExpExecArray | null;
  let n = 0;
  while ((m = re.exec(text))) {
    if (m.index > pos) out.push(text.slice(pos, m.index));
    out.push(m[1] !== undefined ? <strong key={`${key}-${n++}`}>{m[1]}</strong> : <em key={`${key}-${n++}`}>{m[2]}</em>);
    pos = re.lastIndex;
  }
  out.push(text.slice(pos));
  return out;
}

const cells = (row: string) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

export function Markdown({ source }: { source: string }) {
  const lines = source.split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const ln = lines[i];
    const k = `b${i}`;
    if (!ln.trim()) { i++; continue; }
    const h = /^(#{1,3})\s+(.*)$/.exec(ln);
    if (h) {
      const level = h[1].length;
      blocks.push(level === 1 ? <h1 key={k}>{inline(h[2], k)}</h1> : level === 2 ? <h2 key={k}>{inline(h[2], k)}</h2> : <h3 key={k}>{inline(h[2], k)}</h3>);
      i++;
      continue;
    }
    if (ln.trim().startsWith("|") && lines[i + 1]?.trim().startsWith("|---")) {
      const head = cells(ln);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(cells(lines[i++]));
      blocks.push(
        <table key={k}>
          <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, `${k}h${j}`)}</th>)}</tr></thead>
          <tbody>{rows.map((r, a) => <tr key={a}>{r.map((c, j) => <td key={j}>{inline(c, `${k}r${a}c${j}`)}</td>)}</tr>)}</tbody>
        </table>,
      );
      continue;
    }
    if (/^-\s+/.test(ln)) {
      const items: { text: string; sub: string[] }[] = [];
      while (i < lines.length && (/^-\s+/.test(lines[i]) || /^\s{2,}-\s+/.test(lines[i]))) {
        if (/^-\s+/.test(lines[i])) items.push({ text: lines[i].replace(/^-\s+/, ""), sub: [] });
        else items[items.length - 1]?.sub.push(lines[i].replace(/^\s+-\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={k}>{items.map((it, a) => (
          <li key={a}>{inline(it.text, `${k}${a}`)}
            {it.sub.length > 0 && <ul>{it.sub.map((s, b) => <li key={b}>{inline(s, `${k}${a}${b}`)}</li>)}</ul>}
          </li>
        ))}</ul>,
      );
      continue;
    }
    // Paragraph: this line always (whatever it starts with: it matched no block above), then the
    // lines that follow until a blank line or the start of another block.
    const para: string[] = [lines[i++]];
    while (i < lines.length && lines[i].trim() && !/^(#{1,3}\s|-\s|\|)/.test(lines[i])) para.push(lines[i++]);
    blocks.push(<p key={k}>{inline(para.join(" "), k)}</p>);
  }
  return <>{blocks}</>;
}
