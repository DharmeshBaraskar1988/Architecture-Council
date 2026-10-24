// What the room says aloud and with which voice; shared by the room, /api/tts and the avatar renderer
// (avatar/render.py reads voices.json and uses the same clip id).
import type { Speaker } from "./script";
import VOICES from "./voices.json";

/** Microsoft Edge neural voice of each member (edge-tts). */
export const EDGE_VOICE: Record<Exclude<Speaker, "you">, string> = VOICES;

/** Text as a person would say it, split into sentences: short utterances pause naturally and don't cut out in Chrome. */
export function speakable(text: string): string[] {
  const clean = text
    .replace(/https?:\/\/\S+/g, "")
    .replace(/[*_`#>]/g, "")
    .replace(/\s*(→|->)\s*/g, " to ")
    .replace(/\bR([0-7])\b/g, "round $1")
    .replace(/\be\.g\./gi, "for example").replace(/\bi\.e\./gi, "that is").replace(/\bvs\.?\s/gi, "versus ")
    .replace(/\s&\s/g, " and ")
    .replace(/\s*[—–]\s*/g, ", ")
    .replace(/\s*;\s*/g, ", ")
    .replace(/\(([^)]*)\)/g, ", $1,")
    .replace(/\s+,/g, ",").replace(/,+/g, ",").replace(/\s+/g, " ")
    .trim();
  return (clean.match(/[^.!?]+(?:[.!?]+(?=\s|$)|$)/g) ?? [clean]).map((s) => s.replace(/^[\s,]+|[\s,]+$/g, "")).filter(Boolean);
}

/** The one string sent to edge-tts for a line. */
export const spokenText = (text: string) => speakable(text).join(" ");

/** Clip id: sha1 of "voice\ntext". Names both the audio (data/tts) and the talking video (data/avatars/clips). */
export async function clipId(voice: string, text: string): Promise<string> {
  const bytes = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(`${voice}\n${text}`));
  return Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join("");
}
