// Talking-head videos made by avatar/render.py (MuseTalk). Folders under data/avatars:
//   queue/<run>.json      lines waiting for the renderer      clips/<clip id>.mp4   one silent video per spoken line
//   manifests/<run>.json  every line the room asked for        status/<run>.json     the renderer's progress
import { spawn } from "child_process";
import { createHash } from "crypto";
import { existsSync, openSync, promises as fs } from "fs";
import path from "path";
import { REPO_DIR } from "./runs";

export const AVATARS_DIR = path.join(/*turbopackIgnore: true*/ REPO_DIR, "data", "avatars");
export const CLIPS_DIR = path.join(/*turbopackIgnore: true*/ AVATARS_DIR, "clips");
const AVATAR_APP = path.join(/*turbopackIgnore: true*/ REPO_DIR, "avatar");
const PUBLIC_PORTRAITS = path.join(/*turbopackIgnore: true*/ process.cwd(), "public", "avatars");

export interface AvatarLine { speaker: string; voice: string; text: string }
export interface AvatarStatus {
  installed: boolean;                 // MuseTalk environment and weights present
  portraits: string[];                // members with a portrait (public/avatars/<member>.png)
  queued: boolean; rendering: boolean;
  total: number; done: number; failed: number; errors: string[];
  ready: string[];                    // clip ids of this run's lines whose video exists
}

export const clipIdOf = (voice: string, text: string) => createHash("sha1").update(`${voice}\n${text}`).digest("hex");

function python(): string | null {
  for (const p of [path.join(/*turbopackIgnore: true*/ AVATAR_APP, ".venv", "Scripts", "python.exe"),
                   path.join(/*turbopackIgnore: true*/ AVATAR_APP, ".venv", "bin", "python")]) {
    if (existsSync(p)) return p;
  }
  return null;
}

const installed = () => Boolean(python()) && existsSync(path.join(/*turbopackIgnore: true*/ AVATAR_APP, "MuseTalk", "models", "musetalkV15", "unet.pth"));

async function portraits(): Promise<string[]> {
  const files = await fs.readdir(PUBLIC_PORTRAITS).catch(() => [] as string[]);
  return files.filter((f) => f.endsWith(".png")).map((f) => f.slice(0, -4));
}

async function readJson<T>(file: string): Promise<T | null> {
  try { return JSON.parse(await fs.readFile(file, "utf-8")) as T; } catch { return null; }
}

/** Is the renderer process alive? (render.pid holds its process id) */
async function rendering(): Promise<boolean> {
  const pid = Number(await fs.readFile(path.join(/*turbopackIgnore: true*/ AVATARS_DIR, "render.pid"), "utf-8").catch(() => ""));
  if (!pid) return false;
  try { process.kill(pid, 0); return true; } catch { return false; }
}

export async function avatarStatus(run: string): Promise<AvatarStatus> {
  const lines = (await readJson<AvatarLine[]>(path.join(/*turbopackIgnore: true*/ AVATARS_DIR, "manifests", `${run}.json`))) ?? [];
  const st = await readJson<{ total: number; done: number; failed: number; errors?: string[] }>(
    path.join(/*turbopackIgnore: true*/ AVATARS_DIR, "status", `${run}.json`));
  const ready = lines.map((l) => clipIdOf(l.voice, l.text)).filter((id) => existsSync(path.join(/*turbopackIgnore: true*/ CLIPS_DIR, `${id}.mp4`)));
  return {
    installed: installed(), portraits: await portraits(),
    queued: existsSync(path.join(/*turbopackIgnore: true*/ AVATARS_DIR, "queue", `${run}.json`)), rendering: await rendering(),
    total: lines.length, done: st?.done ?? ready.length, failed: st?.failed ?? 0, errors: st?.errors ?? [], ready: [...new Set(ready)],
  };
}

/** Queue a run's lines and start the renderer if it is not running. Lines already rendered are skipped by the renderer. */
export async function queueAvatars(run: string, lines: AvatarLine[]): Promise<AvatarStatus> {
  const exe = python();
  if (!exe || !installed()) return avatarStatus(run);
  const body = JSON.stringify(lines);
  const manifest = path.join(/*turbopackIgnore: true*/ AVATARS_DIR, "manifests", `${run}.json`);
  const same = (await fs.readFile(manifest, "utf-8").catch(() => "")) === body;
  const missing = lines.some((l) => !existsSync(path.join(/*turbopackIgnore: true*/ CLIPS_DIR, `${clipIdOf(l.voice, l.text)}.mp4`)));
  for (const d of ["manifests", "queue", "status", "clips"]) await fs.mkdir(path.join(/*turbopackIgnore: true*/ AVATARS_DIR, d), { recursive: true });
  if (!same) await fs.writeFile(manifest, body, "utf-8");
  const queued = path.join(/*turbopackIgnore: true*/ AVATARS_DIR, "queue", `${run}.json`);
  if (missing && (!same || !existsSync(queued))) await fs.writeFile(queued, body, "utf-8");
  if (missing && !(await rendering())) {
    const log = openSync(path.join(/*turbopackIgnore: true*/ AVATARS_DIR, "render.log"), "a");
    const child = spawn(/*turbopackIgnore: true*/ exe, [path.join(/*turbopackIgnore: true*/ AVATAR_APP, "render.py"), "work"], {
      cwd: AVATAR_APP, detached: true, stdio: ["ignore", log, log], windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" },
    });
    child.unref();
  }
  return avatarStatus(run);
}
