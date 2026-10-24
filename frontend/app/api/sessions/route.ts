import { spawn } from "child_process";
import { existsSync, openSync, promises as fs } from "fs";
import path from "path";
import { NextResponse } from "next/server";
import { REPO_DIR, RUNS_DIR, UPLOADS_DIR } from "@/lib/runs";

const BACKEND = path.join(/*turbopackIgnore: true*/ REPO_DIR, "backend");
const ALLOWED = /\.(md|txt|pdf|docx|html|htm)$/i;
const MAX_BYTES = 10 * 1024 * 1024;

function cli(): string | null {
  if (process.env.COUNCIL_CLI) return process.env.COUNCIL_CLI;
  for (const p of [path.join(/*turbopackIgnore: true*/ BACKEND, ".venv", "Scripts", "council.exe"),
                   path.join(/*turbopackIgnore: true*/ BACKEND, ".venv", "bin", "council")]) {
    if (existsSync(p)) return p;
  }
  return null;
}

function newId(): string {
  const d = new Date();
  const z = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}-${z(d.getHours())}${z(d.getMinutes())}${z(d.getSeconds())}-` +
    Math.random().toString(16).slice(2, 6);
}

// Start a council session on an uploaded PRD. The backend runs in the background
// with `--review skip`, so the session ends at the reviewer gate, waiting for you in the room.
export async function POST(req: Request) {
  const exe = cli();
  if (!exe) return NextResponse.json({ error: "backend not installed: run `pip install -e .` in backend/.venv" }, { status: 500 });

  if (!(req.headers.get("content-type") ?? "").startsWith("multipart/form-data"))
    return NextResponse.json({ error: "upload the PRD as a file" }, { status: 400 });
  const form = await req.formData();
  const file = form.get("file");
  if (!(file instanceof File)) return NextResponse.json({ error: "no file" }, { status: 400 });
  if (!ALLOWED.test(file.name)) return NextResponse.json({ error: "The document must be .pdf, .docx, .html, .md or .txt" }, { status: 400 });
  if (file.size > MAX_BYTES) return NextResponse.json({ error: "PRD is larger than 10 MB" }, { status: 400 });
  // One folder per upload, so the document keeps its own name (the council quotes it by name).
  const folder = path.join(/*turbopackIgnore: true*/ UPLOADS_DIR, String(Date.now()));
  await fs.mkdir(folder, { recursive: true });
  const safe = file.name.replace(/[^\w.-]+/g, "_").slice(-80);
  const prd = path.join(/*turbopackIgnore: true*/ folder, safe);
  await fs.writeFile(prd, Buffer.from(await file.arrayBuffer()));

  const id = newId();
  const dir = path.join(/*turbopackIgnore: true*/ RUNS_DIR, id);
  await fs.mkdir(dir, { recursive: true });
  const out = openSync(path.join(/*turbopackIgnore: true*/ dir, "console.log"), "a");
  const child = spawn(/*turbopackIgnore: true*/ exe, ["run", "--prd", prd, "--review", "skip", "--out", dir], {
    cwd: BACKEND, detached: true, stdio: ["ignore", out, out], windowsHide: true,
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
  });
  child.unref();
  await fs.writeFile(path.join(/*turbopackIgnore: true*/ dir, "session.json"),
                     JSON.stringify({ pid: child.pid, prd: path.basename(prd), started: new Date().toISOString() }, null, 2), "utf-8");
  return NextResponse.json({ id });
}
