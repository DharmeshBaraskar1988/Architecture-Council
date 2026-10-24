"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

const ACCEPT = [".pdf", ".docx", ".html", ".htm", ".md", ".txt"];
const MAX_BYTES = 10 * 1024 * 1024; // same limit as /api/sessions

function checkFile(f: File): string | null {
  const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
  if (!ACCEPT.includes(ext)) return `${f.name} is not a supported type: use ${ACCEPT.join(", ")}`;
  if (f.size > MAX_BYTES) return `${f.name} is larger than 10 MB`;
  if (f.size === 0) return `${f.name} is empty`;
  return null;
}

function size(n: number): string {
  return n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`;
}

// The picked file outlives this component, so going to a session and back still shows it.
// (A File can't go in sessionStorage; this lasts until a full reload.)
let keptFile: File | null = null;

// Start a council session from the browser, then go straight into the room to watch it live.
export default function NewSession() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFileState] = useState<File | null>(keptFile);
  const setFile = (f: File | null) => { keptFile = f; setFileState(f); };
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function pick(f: File | undefined) {
    if (!f) return;
    const problem = checkFile(f);
    setError(problem);
    setFile(problem ? null : f);
    if (input.current) input.current.value = ""; // picking the same file again still fires onChange
  }

  async function start() {
    setBusy(true); setError(null);
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/sessions", { method: "POST", body: form });
    const r = await res.json().catch(() => ({ error: "no answer from the server" }));
    if (r.id) { keptFile = null; router.push(`/runs/${r.id}/room`); }
    else { setError(r.error ?? "could not start"); setBusy(false); }
  }

  const ready = !!file;
  const ext = file ? file.name.slice(file.name.lastIndexOf(".") + 1).toUpperCase() : "";

  return (
    <div className="panel new-session">
      <div>
        <h2>Start a session</h2>
        <p className="muted" style={{ margin: "4px 0 0" }}>
          The council reads the product document and debates live; you watch and listen at the table, and sign at the end.
          About 3 minutes on your API keys (roughly $0.20).
        </p>
      </div>

      {file ? (
        <div className="file-card">
          <span className="file-ext">{ext}</span>
          <div style={{ minWidth: 0 }}>
            <div className="file-name">{file.name}</div>
            <div className="muted" style={{ fontSize: 12.5 }}>
              {size(file.size)}{(ext === "HTML" || ext === "HTM") && " · sections are split at each <h1> and <h2> heading"}
            </div>
          </div>
          <button onClick={() => input.current?.click()} disabled={busy}>Replace</button>
          <button onClick={() => setFile(null)} disabled={busy} aria-label="Remove file">Remove</button>
        </div>
      ) : (
        <div className={`dropzone${dragging ? " over" : ""}`} role="button" tabIndex={0}
             onClick={() => input.current?.click()}
             onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
             onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
             onDragLeave={() => setDragging(false)}
             onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0]); }}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M12 16V4m0 0-4.5 4.5M12 4l4.5 4.5M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div><b>Drop your PRD here</b> or <span className="link">browse</span></div>
          <div className="muted" style={{ fontSize: 12.5 }}>HTML, PDF, Word, Markdown or text · up to 10 MB</div>
        </div>
      )}
      <input ref={input} type="file" accept={ACCEPT.join(",")} hidden onChange={(e) => pick(e.target.files?.[0])} />

      <div className="row">
        <button className="primary" onClick={start} disabled={busy || !ready}>
          {busy ? "Starting…" : "Start and enter the room"}
        </button>
        {error && <span className="chip bad" role="alert">{error}</span>}
      </div>
    </div>
  );
}
