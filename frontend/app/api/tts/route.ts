import { spawn } from "child_process";
import { createHash } from "crypto";
import { existsSync, promises as fs } from "fs";
import path from "path";
import { NextResponse } from "next/server";
import { REPO_DIR } from "@/lib/runs";

// Speech for the council room: Microsoft Edge's neural voices through the free `edge-tts` tool (LGPL-3.0, run as a
// separate program). The text goes to Microsoft's speech service; each clip is cached, so a replay costs nothing.
const BACKEND = path.join(/*turbopackIgnore: true*/ REPO_DIR, "backend");
const CACHE = path.join(/*turbopackIgnore: true*/ REPO_DIR, "data", "tts");
const VOICE = /^[a-z]{2,3}-[A-Z]{2}-[A-Za-z]+Neural$/;
const MAX_CHARS = 4000;

function edgeTts(): string | null {
  if (process.env.COUNCIL_EDGE_TTS) return process.env.COUNCIL_EDGE_TTS;
  for (const p of [path.join(/*turbopackIgnore: true*/ BACKEND, ".venv", "Scripts", "edge-tts.exe"),
                   path.join(/*turbopackIgnore: true*/ BACKEND, ".venv", "bin", "edge-tts")]) {
    if (existsSync(p)) return p;
  }
  return null;
}

function run(exe: string, args: string[]): Promise<string | null> {
  return new Promise((resolve) => {
    const child = spawn(/*turbopackIgnore: true*/ exe, args, { windowsHide: true, env: { ...process.env, PYTHONIOENCODING: "utf-8" } });
    let err = "";
    child.stderr.on("data", (d) => { err += d; });
    const kill = setTimeout(() => { child.kill(); err ||= "timed out"; }, 30_000);
    child.on("error", (e) => { clearTimeout(kill); resolve(e.message); });
    child.on("close", (code) => { clearTimeout(kill); resolve(code === 0 ? null : err.trim().split("\n").pop() || `exit ${code}`); });
  });
}

export async function POST(req: Request) {
  const exe = edgeTts();
  if (!exe) return NextResponse.json({ error: "edge-tts not installed: run `pip install edge-tts` in backend/.venv" }, { status: 501 });
  const body = await req.json().catch(() => null);
  const text = typeof body?.text === "string" ? body.text.trim() : "";
  const voice = typeof body?.voice === "string" ? body.voice : "";
  if (!text || text.length > MAX_CHARS) return NextResponse.json({ error: "text must be 1 to 4000 characters" }, { status: 400 });
  if (!VOICE.test(voice)) return NextResponse.json({ error: "unknown voice" }, { status: 400 });

  const file = path.join(/*turbopackIgnore: true*/ CACHE, `${createHash("sha1").update(`${voice}\n${text}`).digest("hex")}.mp3`);
  if (!existsSync(file)) {
    await fs.mkdir(CACHE, { recursive: true });
    const tmp = `${file}.${process.pid}.${Math.random().toString(16).slice(2)}`;
    await fs.writeFile(`${tmp}.txt`, text, "utf-8");               // a file, not an argument: text may start with "-"
    const err = await run(exe, ["--voice", voice, "--file", `${tmp}.txt`, "--write-media", `${tmp}.mp3`]);
    await fs.unlink(`${tmp}.txt`).catch(() => {});
    if (err) { await fs.unlink(`${tmp}.mp3`).catch(() => {}); return NextResponse.json({ error: err }, { status: 502 }); }
    await fs.rename(`${tmp}.mp3`, file).catch(() => {});            // another request may have finished first
  }
  return new NextResponse(new Uint8Array(await fs.readFile(file)), {
    headers: { "content-type": "audio/mpeg", "cache-control": "private, max-age=86400" },
  });
}
