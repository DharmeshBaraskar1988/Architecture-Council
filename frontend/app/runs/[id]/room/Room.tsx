"use client";

import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import type { CouncilEvent, Decision } from "@/lib/types";
import { buildScript, sayModel, type Intro, type Line, type Speaker, type TableCard } from "@/lib/script";
import { ROUND_TITLES, ROUNDS, type Round } from "@/lib/replay";
import { useStored } from "@/lib/useStored";
import { EDGE_VOICE, speakable, spokenText } from "@/lib/voice";

interface Note { text: string; afterSeq: number; at: string }
interface DocSection { number: number; title: string | null; text: string }
interface TeamMember { agent: string; models: string[]; current: string | null; currentLabel: { model: string; provider: string } | null;
  fellBack: boolean; working: boolean }
interface SeatModel { model: string; provider: string; main: string; fellBack: boolean; working: boolean; used: boolean }
interface Doc { name: string; sections: DocSection[] }

const SEATS: { id: Speaker; name: string; role: string; color: string }[] = [
  { id: "moderator", name: "Mira", role: "Moderator · chair", color: "var(--c-mod)" },
  { id: "strategist", name: "Tara", role: "Strategist", color: "var(--c-str)" },
  { id: "architect", name: "Ada", role: "Architect", color: "var(--c-arch)" },
  { id: "platform_cost", name: "Kabir", role: "Platform & Cost", color: "var(--c-cloud)" },
  { id: "critic", name: "Rex", role: "Critic", color: "var(--c-critic)" },
  { id: "fact_checker", name: "Vera", role: "Fact checker", color: "var(--c-fact)" },
  { id: "you", name: "You", role: "Reviewer", color: "var(--accent)" },
];
const SEAT = Object.fromEntries(SEATS.map((s) => [s.id, s]));
const STANCE: Record<string, string> = { adopt: "adopt", adopt_with_condition: "conditional", reject: "reject" };
const OUTCOME: Record<string, string> = {
  selected: "Selected", selected_with_condition: "Selected with condition", reviewer_decides: "Reviewer decides",
  rejected: "Rejected", parked: "Parked",
};
const THINK_MS = 1700;                              // how long an agent visibly thinks before speaking, at pace 1
const REACTIONS = ["👍", "👎", "❓", "💡"];          // keys 1–4
const STANCE_CHIP: Record<string, string> = { adopt: "good", adopt_with_condition: "warn", reject: "bad" };

/* ---------- characters ---------- */
// Each seat is an illustrated person: shaded skin, real eyes and lips, hair with a highlight, and clothes in the
// seat colour. Skin, hair and eye colours are fixed (they do not change with the theme).
interface Look {
  skin: string; hair: string; iris: string; lips: string; lashes?: boolean; blink: number;
  outfit: "blazer" | "shirt" | "sweater" | "hoodie";
  back?: React.ReactNode; front?: React.ReactNode; shine?: string; beard?: React.ReactNode; props?: React.ReactNode;
  brows?: [string, string];   // left and right, when the default pair does not fit the character
}
const LOOKS: Record<Speaker, Look> = {
  moderator: {   // Mira: dark bob and a headset
    skin: "#EFC3A0", hair: "#3B2A20", iris: "#5B3A24", lips: "#C2575E", lashes: true, blink: 0, outfit: "blazer",
    back: <path d="M18 28c0-9 6-15 14-15s14 6 14 15v13c0 2-2 3-4 3h-1V30H23v14h-1c-2 0-4-1-4-3z" />,
    front: <path d="M19.5 30C19 20 24 15 32 15s13 5 12.5 15c-2-5-6-8-12.5-8S21.5 25 19.5 30z" />,
    shine: "M24.5 18.5q4-2.6 9-2.2",
    props: <g stroke="#2B2F3A" fill="none" strokeLinecap="round"><path d="M18.5 29a13.5 13.5 0 0 1 27 0" strokeWidth="1.8" />
      <rect x="16.6" y="27" width="4" height="8" rx="2" fill="#2B2F3A" stroke="none" /><path d="M18.6 34.5q1.5 5.5 8 5" strokeWidth="1.1" />
      <circle cx="26.8" cy="39.5" r="1.2" fill="#2B2F3A" stroke="none" /></g>,
  },
  strategist: {  // Tara: long black hair, side fringe, gold earrings
    skin: "#C08260", hair: "#1C1418", iris: "#3A2416", lips: "#A8454E", lashes: true, blink: 1.3, outfit: "sweater",
    back: <path d="M18 30c0-10 6-16 14-16s14 6 14 16l1.5 22h-31z" />,
    front: <path d="M19.5 30C19 20 24 15 32 15s13 5 12.5 15c-3-6-9-9-17-6-3 1-6 3-7.5 6z" />,
    shine: "M23.5 20q3-3.4 8.5-3.8",
    props: <><circle cx="19.9" cy="34.6" r="1.1" fill="#E7B53C" /><circle cx="44.1" cy="34.6" r="1.1" fill="#E7B53C" />
      <path d="M26.5 49.5q5.5 5 11 0" fill="none" stroke="#E7B53C" strokeWidth=".7" /><circle cx="32" cy="53.2" r=".9" fill="#E7B53C" /></>,
  },
  architect: {   // Ada: auburn pixie cut and round glasses
    skin: "#F4D0B5", hair: "#8A3B1F", iris: "#3F7A5A", lips: "#C6626A", lashes: true, blink: 2.1, outfit: "blazer",
    front: <path d="M19.5 29C19 19 24 14.5 32 14.5s13 4.5 12.5 13c-4-1-8-4-10-7-3 4-9 7-15 8.5z" />,
    shine: "M26 17.5q4-2.2 8.5-1.6",
    props: <g fill="none" stroke="#3A2A20" strokeWidth=".9"><circle cx="27" cy="30.5" r="3.8" fill="#fff" fillOpacity=".12" />
      <circle cx="37" cy="30.5" r="3.8" fill="#fff" fillOpacity=".12" /><path d="M30.8 30.1q1.2-.9 2.4 0M23.2 30l-2.9-1M40.8 30l2.9-1" /></g>,
  },
  platform_cost: { // Kabir: short black hair, full beard and moustache
    skin: "#A56C4A", hair: "#17130F", iris: "#2E1D12", lips: "#8E4A44", blink: .6, outfit: "shirt",
    front: <path d="M20 28c-.5-8.5 5-13.5 12-13.5S44.5 19.5 44 28c-2-3.5-6-5.5-12-5.5S22 24.5 20 28z" />,
    shine: "M25 18.2q4-2 9-1.2",
    beard: <><path d="M20.3 31c.6 8.4 5.5 14 11.7 14s11.1-5.6 11.7-14c-1.5 4.6-3.8 7.4-6.2 8.2-.8-2-2.8-3.1-5.5-3.1s-4.7 1.1-5.5 3.1c-2.4-.8-4.7-3.6-6.2-8.2z" />
      <path d="M27.6 37.6q4.4-2.8 8.8 0q-1.8.4-4.4-.5-2.6.9-4.4.5z" /></>,
  },
  critic: {      // Rex: spiky blond hair, one sceptical eyebrow, stubble
    skin: "#E6B592", hair: "#C9963A", iris: "#4E7DA6", lips: "#B8676A", blink: 2.8, outfit: "shirt",
    front: <path d="M19.5 29l-1.5-9 4.5 2 1-7.5 4.5 4.5 3.5-7.5 3 6.5 4.5-5.5 1.5 6.5 4.5-2-1.5 7.5 1.5 4.5c-3-4-8-7-13.5-7S22 25 19.5 29z" />,
    brows: ["M23.8 26.3l6.3 1.5-.25.95-6.25-1.25z", "M40.4 25.4q-3-2.6-6.5-.5l.3.9q3-1.6 6-.4z"],
    beard: <path d="M21 34c1.5 6.5 5.5 10.6 11 10.6s9.5-4.1 11-10.6c-1 3-3.6 5.6-6 6.2-1-1.6-2.8-2.6-5-2.6s-4 1-5 2.6c-2.4-.6-5-3.2-6-6.2z" opacity=".22" />,
  },
  fact_checker: { // Vera: curly hair and a magnifying glass
    skin: "#8A573A", hair: "#24160F", iris: "#3B2213", lips: "#7E3B3E", lashes: true, blink: 1.8, outfit: "sweater",
    back: <><circle cx="19.5" cy="30" r="4.8" /><circle cx="44.5" cy="30" r="4.8" /><circle cx="19" cy="37" r="4.2" /><circle cx="45" cy="37" r="4.2" /></>,
    front: <><circle cx="22" cy="22.5" r="4.8" /><circle cx="26.5" cy="18.2" r="4.8" /><circle cx="32" cy="16.6" r="4.8" />
      <circle cx="37.5" cy="18.2" r="4.8" /><circle cx="42" cy="22.5" r="4.8" /></>,
    shine: "M24.5 17q1.5-1.6 3.5-1.6M30.5 14.2q1.5-1 3.2-.6M36.5 15.8q1.6-.5 3 .4",
    props: <g><path d="M49.5 53.5l4 4" stroke="#5A3A22" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="46" cy="50" r="4.4" fill="#DDF3FF" fillOpacity=".5" stroke="#2B2F3A" strokeWidth="1.6" />
      <path d="M43.6 48.4q1-1.6 2.8-1.8" fill="none" stroke="#fff" strokeWidth=".8" strokeLinecap="round" /></g>,
  },
  you: {         // the reviewer: a hoodie, seen from the room
    skin: "#D6AC88", hair: "#5A4636", iris: "#4A3626", lips: "#B56E66", blink: 3.4, outfit: "hoodie",
    back: <path d="M16.5 52c0-21 7-35.5 15.5-35.5S47.5 31 47.5 52z" fill="var(--accent)" />,
    front: <path d="M20 27.5c-.5-8 5-13 12-13s12.5 5 12 13c-2-3.5-6-5.5-12-5.5s-10 2-12 5.5z" />,
    shine: "M25 18.4q4-2 8.5-1.4",
  },
};

/** Lighter (t > 0) or darker (t < 0) version of a #rrggbb colour. */
function shade(hex: string, t: number): string {
  const n = parseInt(hex.slice(1), 16);
  const to = t < 0 ? 0 : 255;
  return "#" + [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.round(v + (to - v) * Math.abs(t)).toString(16).padStart(2, "0")).join("");
}

const FACE = "M20 28.5c0-8.3 5.4-14 12-14s12 5.7 12 14c0 4.2-.7 7.6-2.2 10.3-2.2 3.9-5.6 5.9-9.8 5.9s-7.6-2-9.8-5.9C20.7 36.1 20 32.7 20 28.5z";
const MIRROR = "translate(64 0) scale(-1 1)";       // the right half of the face is the left half, flipped

/** Members with a 3D portrait in public/avatars (made by avatar/make_portraits.py). */
const PhotosCtx = createContext<Set<string>>(new Set());

/** A member's face: their 3D portrait, which moves with their voice while they speak, or the illustrated one. */
function Face({ id, speaking }: { id: Speaker; speaking: boolean }) {
  const photos = useContext(PhotosCtx);
  if (!photos.has(id)) return <Cartoon id={id} speaking={speaking} />;
  return (
    <span className={`portrait ${speaking ? "talking" : ""}`} style={{ ["--who" as string]: SEAT[id].color }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={`/avatars/${id}.png`} alt="" />
    </span>
  );
}

function Cartoon({ id, speaking }: { id: Speaker; speaking: boolean }) {
  const c = SEAT[id].color;
  const look = LOOKS[id];
  const p = `face-${useId().replace(/:/g, "")}`;
  const line = shade(look.skin, -0.35);
  const eye = (
    <g>
      <path d="M24.3 30.5q2.7-2.5 5.4 0q-2.7 2.1-5.4 0z" fill="#F7F3EF" />
      <g clipPath={`url(#${p}-eye)`}>
        <circle cx="27" cy="30.45" r="1.3" fill={look.iris} stroke={shade(look.iris, -0.45)} strokeWidth=".3" />
        <circle cx="27" cy="30.45" r=".6" fill="#111" /><circle cx="27.45" cy="30" r=".36" fill="#fff" />
      </g>
      <path d="M24.1 30.5q2.9-2.8 5.8 0" fill="none" stroke="#2A1C16" strokeWidth=".75" strokeLinecap="round" />
      {look.lashes && <path d="M29.5 30.1l.9-.6M29 29.5l.6-.8" stroke="#2A1C16" strokeWidth=".45" strokeLinecap="round" />}
      <path d="M24.7 31.1q2.3 1.3 4.6 0" fill="none" stroke={line} strokeWidth=".35" opacity=".7" />
    </g>
  );
  return (
    <svg viewBox="0 0 64 64" aria-hidden="true" className={`face ${speaking ? "talking" : ""}`}>
      <defs>
        <clipPath id={`${p}-clip`}><circle cx="32" cy="34" r="27" /></clipPath>
        <clipPath id={`${p}-eye`}><path d="M24.3 30.5q2.7-2.5 5.4 0q-2.7 2.1-5.4 0z" /></clipPath>
        <radialGradient id={`${p}-skin`} cx=".42" cy=".36" r=".72">
          <stop offset="0" stopColor={shade(look.skin, 0.14)} /><stop offset=".6" stopColor={look.skin} /><stop offset="1" stopColor={shade(look.skin, -0.2)} />
        </radialGradient>
        <linearGradient id={`${p}-hair`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={shade(look.hair, 0.22)} /><stop offset="1" stopColor={shade(look.hair, -0.25)} />
        </linearGradient>
        <radialGradient id={`${p}-cloth`} cx=".5" cy="0" r="1">
          <stop offset="0" stopColor="#fff" stopOpacity=".22" /><stop offset=".6" stopColor="#000" stopOpacity="0" /><stop offset="1" stopColor="#000" stopOpacity=".3" />
        </radialGradient>
      </defs>
      <circle cx="32" cy="34" r="27" fill={c} fillOpacity=".14" />
      <g clipPath={`url(#${p}-clip)`}>
        <g fill={`url(#${p}-hair)`}>{look.back}</g>

        {/* shoulders and outfit */}
        <path d="M7 66c0-12 10-17.5 25-17.5S57 54 57 66z" fill={c} />
        {look.outfit === "blazer" && <>
          <path d="M27 48.6l5 9.5 5-9.5z" fill="#F4F6F8" />
          <path d="M26.6 48.8l5.4 10-3.4 7.4L20.5 52zM37.4 48.8L32 58.8l3.4 7.4L43.5 52z" fill={c} stroke="#000" strokeOpacity=".28" strokeWidth=".6" />
        </>}
        {look.outfit === "shirt" && <>
          <path d="M27.4 48.4l4.6 6 4.6-6z" fill={shade(look.skin, -0.06)} />
          <path d="M27.2 48.2l4.8 6-3.4 3-3.6-6.4zM36.8 48.2l-4.8 6 3.4 3 3.6-6.4z" fill="#fff" fillOpacity=".38" stroke="#000" strokeOpacity=".2" strokeWidth=".5" />
          <circle cx="32" cy="58" r=".6" fill="#000" fillOpacity=".3" /><circle cx="32" cy="62" r=".6" fill="#000" fillOpacity=".3" />
        </>}
        {look.outfit === "sweater" && <path d="M26.3 48.8q5.7 4.6 11.4 0" fill="none" stroke="#000" strokeOpacity=".22" strokeWidth="2" />}
        {look.outfit === "hoodie" && <path d="M29.5 50v7M34.5 50v7" stroke="#fff" strokeOpacity=".8" strokeWidth=".8" strokeLinecap="round" />}
        <path d="M7 66c0-12 10-17.5 25-17.5S57 54 57 66z" fill={`url(#${p}-cloth)`} />

        <g className="head">
          {/* neck, with the shadow the chin casts */}
          <path d="M27.5 38h9v12.5q-4.5 2-9 0z" fill={shade(look.skin, -0.1)} />
          <path d="M27.5 41.5q4.5 4.2 9 0v3.6q-4.5 2.6-9 0z" fill="#000" opacity=".16" />
          {/* ears */}
          <g fill={`url(#${p}-skin)`}><ellipse cx="20.2" cy="30.6" rx="2.2" ry="3.2" /><ellipse cx="43.8" cy="30.6" rx="2.2" ry="3.2" /></g>
          <path d="M20.6 29q-1 1.6 0 3.2M43.4 29q1 1.6 0 3.2" fill="none" stroke={line} strokeWidth=".5" opacity=".6" />
          <path d={FACE} fill={`url(#${p}-skin)`} />
          <ellipse cx="24.6" cy="35" rx="2.4" ry="1.5" fill="#FF6B6B" opacity=".18" />
          <ellipse cx="39.4" cy="35" rx="2.4" ry="1.5" fill="#FF6B6B" opacity=".18" />

          <g className="eyes" style={{ animationDelay: `${look.blink}s` }}>{eye}<g transform={MIRROR}>{eye}</g></g>
          {look.brows
            ? <g fill={look.hair}><path d={look.brows[0]} /><path d={look.brows[1]} /></g>
            : <g fill={look.hair}><path d="M23.6 27.4q2.8-2.3 6.4-.9l-.25.95q-3.1-.9-5.9.6z" /><path transform={MIRROR} d="M23.6 27.4q2.8-2.3 6.4-.9l-.25.95q-3.1-.9-5.9.6z" /></g>}

          {/* nose */}
          <path d="M30.7 29.6q-.5 3.4.2 5.2" fill="none" stroke={line} strokeWidth=".55" opacity=".55" strokeLinecap="round" />
          <circle cx="32.4" cy="34" r=".8" fill="#fff" opacity=".22" />
          <path d="M30.1 35.2q1.9 1.5 3.8 0" fill="none" stroke={line} strokeWidth=".5" opacity=".55" strokeLinecap="round" />
          <path d="M30.6 35.6q.6.4 1.1.1M33.4 35.6q-.6.4-1.1.1" fill="none" stroke={shade(look.skin, -0.5)} strokeWidth=".5" strokeLinecap="round" />

          {look.beard && <g fill={`url(#${p}-hair)`}>{look.beard}</g>}

          {/* lips at rest; while talking an open mouth whose height follows the voice */}
          <g className="smile">
            <path d="M28.5 38.7q1.6-1.3 3.5-.6q1.9-.7 3.5.6q-3.5.6-7 0z" fill={look.lips} />
            <path d="M28.6 38.75q3.4.7 6.8 0q-.9 2.2-3.4 2.2t-3.4-2.2z" fill={shade(look.lips, 0.12)} />
            <path d="M28.5 38.72q3.5.7 7 0" fill="none" stroke={shade(look.lips, -0.4)} strokeWidth=".45" strokeLinecap="round" />
            <path d="M31 40.1q1 .3 2 0" fill="none" stroke="#fff" strokeOpacity=".35" strokeWidth=".4" strokeLinecap="round" />
          </g>
          <g className="mouth">
            <ellipse cx="32" cy="39" rx="3" ry="1.9" fill="#3A1218" stroke={look.lips} strokeWidth=".9" />
            <rect x="29.7" y="37.5" width="4.6" height=".95" rx=".4" fill="#F4F1EC" />
            <ellipse cx="32" cy="40.1" rx="1.7" ry=".65" fill="#C9505F" />
          </g>

          <g fill={`url(#${p}-hair)`}>{look.front}</g>
          {look.shine && <path d={look.shine} fill="none" stroke={shade(look.hair, 0.45)} strokeWidth=".8" strokeLinecap="round" opacity=".7" />}
          {look.props}
        </g>
      </g>
      <circle className="ring" cx="32" cy="34" r="27" fill="none" stroke={c} strokeWidth={speaking ? 3 : 1.5} />
    </svg>
  );
}

/** Cartoon thought cloud above a seat. `working`: the agent is busy right now (live), so the dots move. */
function Cloud({ text, working, own }: { text: string; working?: boolean; own?: boolean }) {
  return (
    <div className={`cloud ${working ? "working" : ""}`} role="note" aria-label="thinking">
      <span className="cloud-text">{text}</span>
      {working && <span className="dots"><i /><i /><i /></span>}
      {!working && own === false && <span className="cloud-src">facts in front of them</span>}
      <span className="puff p1" /><span className="puff p2" />
    </div>
  );
}

/* ---------- voice ---------- */
// Main voice: Microsoft's neural voices through edge-tts (free; /api/tts makes and caches the clips).
// If that is not installed or the machine is offline, the browser's own voices take over.

/** Plays clips through one <audio> and measures how loud the voice is, so the speaker's mouth opens with it. */
class Speech {
  private audio: HTMLAudioElement | null = null;
  private meter: { ctx: AudioContext; an: AnalyserNode; buf: Uint8Array<ArrayBuffer> } | null = null;
  private clips = new Map<string, Promise<string | null>>();
  private frame = 0;

  /** The clip's object URL, or null if edge-tts could not make it. Asked once per line; later calls reuse it. */
  clip(who: Speaker, text: string): Promise<string | null> {
    const voice = EDGE_VOICE[who as Exclude<Speaker, "you">];
    if (!voice) return Promise.resolve(null);
    const key = `${voice}\n${text}`;
    let p = this.clips.get(key);
    if (!p) {
      p = fetch("/api/tts", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ voice, text }) })
        .then(async (r) => (r.ok ? URL.createObjectURL(await r.blob()) : null)).catch(() => null);
      p.then((u) => { if (!u) this.clips.delete(key); });          // try again next time
      this.clips.set(key, p);
    }
    return p;
  }

  /** Call from a click: browsers only allow sound after the person has interacted with the page. */
  unlock() {
    if (!this.audio) this.audio = new Audio();
    try {
      if (!this.meter) {
        const ctx = new AudioContext();
        const an = ctx.createAnalyser();
        an.fftSize = 512;
        ctx.createMediaElementSource(this.audio).connect(an);
        an.connect(ctx.destination);
        this.meter = { ctx, an, buf: new Uint8Array(an.fftSize) };
      }
      void this.meter.ctx.resume();
    } catch { /* no Web Audio: the mouth uses the plain animation */ }
  }

  play(url: string, rate: number, onEnd: () => void, onFail: () => void) {
    this.unlock();
    const a = this.audio!;
    a.src = url;
    a.playbackRate = rate;                         // browsers keep the pitch when speeding up
    a.onended = () => { this.still(); onEnd(); };
    a.onerror = () => { this.still(); onFail(); };
    a.play().then(() => this.lipSync()).catch(() => { this.still(); onFail(); });
  }

  stop() { if (this.audio) { this.audio.onended = this.audio.onerror = null; this.audio.pause(); } this.still(); }

  private lipSync() {
    const m = this.meter, root = document.documentElement;
    if (!m) return;
    root.dataset.lipsync = "";
    const tick = () => {
      m.an.getByteTimeDomainData(m.buf);
      let sum = 0;
      for (const v of m.buf) sum += (v - 128) ** 2;
      const level = Math.sqrt(sum / m.buf.length) / 128;
      root.style.setProperty("--mouth", Math.min(1.35, Math.max(0.15, (level - 0.015) * 9)).toFixed(2));
      this.frame = requestAnimationFrame(tick);
    };
    cancelAnimationFrame(this.frame);
    tick();
  }

  private still() {
    cancelAnimationFrame(this.frame);
    if (typeof document !== "undefined") { delete document.documentElement.dataset.lipsync; document.documentElement.style.removeProperty("--mouth"); }
  }
}

/* fallback: the browser's own speech (Edge's "Natural" voices sound the most human) */
// Voices each character would like, best first. Names are matched as words inside the browser's voice name.
const VOICE_WISH: Record<Exclude<Speaker, "you">, { female: boolean; names: string[] }> = {
  moderator:     { female: true,  names: ["Aria", "Jenny", "Ava", "Emma", "Samantha", "Google US English", "Zira"] },
  strategist:    { female: true,  names: ["Neerja", "Heera", "Sonia", "Libby", "Google UK English Female", "Hazel", "Veena"] },
  architect:     { female: true,  names: ["Sonia", "Libby", "Maisie", "Natasha", "Karen", "Hazel", "Moira", "Tessa", "Google UK English Female"] },
  platform_cost: { female: false, names: ["Prabhat", "Ravi", "Rishi", "Guy", "Davis", "Google UK English Male", "Daniel", "David"] },
  critic:        { female: false, names: ["Ryan", "Christopher", "Eric", "Andrew", "Brian", "Thomas", "George", "Mark", "Alex", "Fred"] },
  fact_checker:  { female: true,  names: ["Michelle", "Natasha", "Clara", "Emma", "Jenny", "Ava", "Victoria", "Google US English", "Zira"] },
};
const FEMALE = /\b(female|aria|jenny|ava|emma|samantha|zira|neerja|heera|sonia|libby|maisie|natasha|karen|hazel|moira|tessa|veena|michelle|clara|victoria|ana|susan|catherine|linda|eva|nancy|sara|jane|elizabeth)\b/i;
const MALE = /\b(male|guy|davis|daniel|david|prabhat|ravi|rishi|ryan|christopher|eric|andrew|brian|thomas|george|mark|alex|fred|james|richard|roger|steffan|william|liam|tony)\b/i;

/** Neural voices first, then Google's online voices, then the rest. */
const quality = (v: SpeechSynthesisVoice) =>
  (/natural|neural|premium|enhanced/i.test(v.name) ? 100 : 0) + (/online/i.test(v.name) ? 20 : 0) + (/google/i.test(v.name) ? 40 : 0);

/** One distinct voice per character where the machine has enough; a shared voice gets a slight pitch change. */
function castVoices(all: SpeechSynthesisVoice[]): Partial<Record<Speaker, { voice: SpeechSynthesisVoice; pitch: number }>> {
  const voices = [...all].sort((a, b) => quality(b) - quality(a));
  const used = new Map<string, number>();
  const out: Partial<Record<Speaker, { voice: SpeechSynthesisVoice; pitch: number }>> = {};
  for (const [who, wish] of Object.entries(VOICE_WISH) as [Speaker, typeof VOICE_WISH.moderator][]) {
    const free = voices.filter((v) => !used.has(v.name));
    const byName = wish.names.map((n) => free.find((v) => new RegExp(`\\b${n}\\b`, "i").test(v.name))).find(Boolean);
    const sameGender = (v: SpeechSynthesisVoice) => (wish.female ? FEMALE.test(v.name) && !/\bmale\b/i.test(v.name) : MALE.test(v.name));
    const voice = byName ?? free.find(sameGender) ?? free[0] ?? voices.find(sameGender) ?? voices[0];
    if (!voice) continue;
    const n = used.get(voice.name) ?? 0;
    used.set(voice.name, n + 1);
    out[who] = { voice, pitch: n === 0 ? 1 : 1 + (n % 2 ? -0.08 : 0.08) * Math.ceil(n / 2) };
  }
  return out;
}

function useVoices() {
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const load = () => setVoices(speechSynthesis.getVoices().filter((v) => /^en/i.test(v.lang)));
    load();
    speechSynthesis.addEventListener("voiceschanged", load);
    return () => speechSynthesis.removeEventListener("voiceschanged", load);
  }, []);
  return voices;
}


export default function Room({ id, initial, names: initialNames, decision: initialDecision, notes: initialNotes,
                               running: initiallyRunning, startTurn = -1, document: initialDoc, photos = [] }: {
  id: string; initial: CouncilEvent[]; names: Record<string, string>; decision: Decision | null; notes: Note[];
  running: boolean; startTurn?: number; document: Doc | null; photos?: string[];
}) {
  const [log, setLog] = useState(initial);
  const [names, setNames] = useState(initialNames);
  const [decision, setDecision] = useState(initialDecision);
  const [notes, setNotes] = useState(initialNotes);
  const [running, setRunning] = useState(initiallyRunning);
  const [doc, setDoc] = useState(initialDoc);
  // Who sits at the table (from team.json): older sessions recorded no introductions, so the script uses these.
  const [intros, setIntros] = useState<Intro[]>([]);
  const lines = useMemo(() => buildScript(log, names, decision, intros), [log, names, decision, intros]);

  // line being spoken; -1 = not started. ?turn=N in the URL opens paused on turn N (?turn=end: the last);
  // otherwise coming back to the room resumes (paused) where you left it.
  const [idx, setIdx] = useStored(`room:${id}:idx`, startTurn < 0 ? -1 : Math.min(startTurn, Math.max(lines.length - 1, 0)), startTurn >= 0);
  const [playing, setPlaying] = useState(false);
  const [phase, setPhase] = useState<"think" | "speak" | null>(null);
  const [voiceOn, setVoiceOn] = useStored("room:voice", true);
  const [speed, setSpeed] = useStored("room:speed", 1.25);
  const [speaking, setSpeaking] = useState<Speaker | null>(null);
  const [hand, setHand] = useStored(`room:${id}:hand`, false);
  const [draft, setDraft] = useStored(`room:${id}:draft`, "");
  const [ack, setAck] = useState<string | null>(null);
  const [tab, setTab] = useStored<"talk" | "stand">(`room:${id}:tab`, "talk");
  // The person you clicked: their profile, and only their turns in the conversation and on the timeline.
  const [focus, setFocus] = useState<Speaker | null>(null);
  // Your reaction to each turn (by line key), and the emoji that floats up from the speaker when you react.
  const [reactions, setReactions] = useStored<Record<string, string>>(`room:${id}:reactions`, {});
  const [burst, setBurst] = useState<{ who: Speaker; emoji: string; n: number } | null>(null);
  const voices = useVoices();
  const casting = useMemo(() => castVoices(voices), [voices]);
  const [engine, setEngine] = useStored<"edge" | "browser">("room:engine", "edge");
  const speech = useRef<Speech | null>(null);
  if (typeof window !== "undefined" && !speech.current) speech.current = new Speech();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const token = useRef(0);
  const transcript = useRef<HTMLDivElement>(null);

  // Live: while the backend works, pick up new events every 1.5 s.
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const r = await fetch(`/api/runs/${id}/events?after=0`, { cache: "no-store" }).then((x) => x.json()).catch(() => null);
      if (!r || r.error) return;
      setLog(r.events); setNames(r.names); setDecision(r.decision); setNotes(r.notes); setRunning(r.running);
      if (r.document) setDoc(r.document);
    }, 1500);
    return () => clearInterval(t);
  }, [running, id]);

  // Which LLM each agent is on: read once on entry, then live while the session runs.
  const [team, setTeam] = useState<Record<string, SeatModel>>({});
  useEffect(() => {
    const load = async () => {
      const r = await fetch(`/api/runs/${id}/team`, { cache: "no-store" }).then((x) => x.json()).catch(() => null);
      if (!r?.members) return;
      setIntros((was) => (was.length ? was : r.members.map((m: TeamMember & Intro) => ({ agent: m.agent, name: m.name, role: m.role,
        specialty: m.specialty, works_on: m.works_on, votes: m.votes, models: m.models })).filter((m: Intro) => m.specialty)));
      setTeam(Object.fromEntries(r.members.filter((m: TeamMember) => m.currentLabel || m.models[0]).map((m: TeamMember) => [m.agent, {
        model: m.currentLabel?.model ?? m.models[0]?.split("/").slice(1).join("/") ?? "",
        provider: m.currentLabel?.provider ?? m.models[0]?.split("/")[0] ?? "",
        main: m.models[0] ?? "", fellBack: m.fellBack, working: m.working, used: Boolean(m.current),
      }])));
    };
    load();
    if (!running) return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [running, id]);

  const stopVoice = () => { speech.current?.stop(); try { speechSynthesis.cancel(); } catch { /* no speech support */ } };
  useEffect(() => stopVoice, []);                  // leaving the room silences it; the position is kept for your return

  // Make the next turns' clips while this one plays, so there is no gap between speakers.
  useEffect(() => {
    if (!voiceOn || engine !== "edge" || idx < 0) return;
    for (const l of lines.slice(idx, idx + 3)) if (l.speaker !== "you") speech.current?.clip(l.speaker, spokenText(l.text));
  }, [voiceOn, engine, idx, lines]);

  const say = useCallback((who: Speaker, text: string, done: () => void) => {
    const my = ++token.current;
    const finish = () => { if (my !== token.current) return; if (timer.current) clearTimeout(timer.current); setSpeaking(null); setPhase(null); done(); };
    setSpeaking(who); setPhase("speak");
    const words = text.split(/\s+/).length;
    const parts = speakable(text);
    const browserSay = () => sayInBrowser(my, who, parts, words, finish);
    if (voiceOn && parts.length && engine === "edge" && speech.current && who !== "you") {
      stopVoice();
      speech.current.clip(who, parts.join(" ")).then((url) => {
        if (my !== token.current) return;
        if (!url) { browserSay(); return; }
        speech.current!.play(url, rate, () => setTimeout(finish, 300), browserSay);
      });
      timer.current = setTimeout(finish, (words * 650 + 12000) / speed);   // safety net: generating plus speaking
    } else {
      browserSay();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceOn, casting, speed, engine]);
  const rate = Math.min(0.95 + (speed - 1) * 0.45, 1.6);
  const photoSet = useMemo(() => new Set(photos), [photos]);

  /** The browser's own voices, sentence by sentence (fallback, or chosen in the controls). */
  const sayInBrowser = (my: number, who: Speaker, parts: string[], words: number, finish: () => void) => {
    if (my !== token.current) return;
    if (timer.current) clearTimeout(timer.current);
    if (voiceOn && parts.length && typeof window !== "undefined" && "speechSynthesis" in window && who !== "you") {
      stopVoice();
      const cast = casting[who];
      parts.forEach((part, k) => {
        const u = new SpeechSynthesisUtterance(part);
        if (cast) { u.voice = cast.voice; u.lang = cast.voice.lang; u.pitch = cast.pitch; }
        u.rate = Math.min(0.95 + (speed - 1) * 0.5, 1.8);
        if (k === parts.length - 1) u.onend = () => setTimeout(finish, 350);
        u.onerror = (ev) => { if (ev.error !== "interrupted" && ev.error !== "canceled") setTimeout(finish, 250); };
        speechSynthesis.speak(u);                    // queued: one sentence after another
      });
      timer.current = setTimeout(finish, (words * 600 + parts.length * 400 + 5000) / speed);   // safety net if the voice stalls
    } else {
      timer.current = setTimeout(finish, Math.max(1500, words * 280) / speed);
    }
  };

  // The conversation: the speaker thinks (cloud), then speaks; then the next turn. At the end of a live run, wait.
  useEffect(() => {
    if (!playing || idx < 0) return;
    if (idx >= lines.length) { if (!running) setPlaying(false); return; }
    const l = lines[idx];
    const my = ++token.current;
    if (l.thoughts?.[l.speaker] && l.speaker !== "moderator") {
      setSpeaking(l.speaker); setPhase("think");
      timer.current = setTimeout(() => { if (my === token.current) say(l.speaker, l.text, () => setIdx((i) => i + 1)); }, THINK_MS / speed);
    } else {
      say(l.speaker, l.text, () => setIdx((i) => i + 1));
    }
    return () => { token.current++; if (timer.current) clearTimeout(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, idx, lines.length > idx]);

  useEffect(() => { transcript.current?.scrollTo({ top: transcript.current.scrollHeight }); }, [idx, notes.length, ack]);

  const pause = () => { setPlaying(false); token.current++; stopVoice(); if (timer.current) clearTimeout(timer.current); setSpeaking(null); setPhase(null); };
  const play = () => { speech.current?.unlock(); if (idx < 0 || (idx >= lines.length && !running)) setIdx(0); setPlaying(true); };
  const skip = () => { pause(); setIdx((i) => Math.min(Math.max(i, 0) + 1, lines.length)); setTimeout(() => setPlaying(true), 50); };
  const toEnd = () => { pause(); setIdx(lines.length); };
  /** Go to turn `i`: paused there, or carrying on from there if the room was playing. */
  const jump = (i: number) => {
    const was = playing;
    pause(); setIdx(Math.max(0, Math.min(i, lines.length - 1)));
    if (was) setTimeout(() => setPlaying(true), 50);
  };
  const back = () => jump(Math.min(idx, lines.length) - 1);

  const shown = idx < 0 ? 0 : Math.min(idx + 1, lines.length);
  const current: Line | undefined = idx >= 0 && lines.length ? lines[Math.min(idx, lines.length - 1)] : undefined;
  const upTo = current?.upTo ?? 0;
  const round: Round | null = current?.round ?? null;
  const decided = log.some((e) => e.type === "stage.decided");
  const signed = log.find((e) => e.type === "reviewer.signed");
  const atGate = decided && !signed && !running && idx >= lines.length - 1 && idx >= 0;
  const caughtUp = running && idx >= lines.length - 1;

  const react = (emoji: string) => {
    if (!current) return;
    const key = current.key;
    setReactions((r) => { const next = { ...r }; if (next[key] === emoji) delete next[key]; else next[key] = emoji; return next; });
    if (reactions[key] !== emoji) {
      const n = Date.now();
      setBurst({ who: current.speaker, emoji, n });
      setTimeout(() => setBurst((b) => (b?.n === n ? null : b)), 1200);
    }
  };
  const clickSeat = (who: Speaker) => {
    if (who === "you") { pause(); setHand((h) => !h); return; }   // your own seat: raise (or lower) your hand
    setFocus((f) => (f === who ? null : who));
  };

  // Keyboard: space plays or pauses, arrows step through turns, 1–4 react, H raises your hand, Esc clears the focus.
  const keys = useRef({ playing, play, pause, skip, back, react, idx, hand: () => clickSeat("you"), unfocus: () => setFocus(null) });
  keys.current = { playing, play, pause, skip, back, react, idx, hand: () => clickSeat("you"), unfocus: () => setFocus(null) };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || (e.target as HTMLElement).closest?.("input, textarea, select, [contenteditable]")) return;
      const k = keys.current;
      if (e.key === " ") { e.preventDefault(); if (k.playing) k.pause(); else k.play(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); if (k.idx < 0) k.play(); else k.skip(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); k.back(); }
      else if (/^[1-4]$/.test(e.key)) k.react(REACTIONS[Number(e.key) - 1]);
      else if (e.key === "h" || e.key === "H") { e.preventDefault(); k.hand(); }
      else if (e.key === "Escape") k.unfocus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Topic: the subject of this turn, or the last one discussed in this round.
  const topic = useMemo(() => {
    for (let k = Math.min(idx, lines.length - 1); k >= 0; k--) {
      if (lines[k].round !== round) break;
      if (lines[k].topic) return lines[k].topic;
    }
    return undefined;
  }, [idx, lines, round]);

  // Thought clouds: this turn's, or (live, caught up) everyone the backend says is working right now.
  const working = useMemo(() => {
    if (!caughtUp) return null;
    const last = [...log].reverse().find((e) => e.type === "round.started");
    return last ? { agents: last.payload.agents as string[], doing: last.payload.doing as string, round: last.payload.round as Round } : null;
  }, [caughtUp, log]);
  const clouds: Partial<Record<Speaker, { text: string; working?: boolean; own?: boolean }>> = {};
  if (current?.thoughts) {
    for (const [a, txt] of Object.entries(current.thoughts)) {
      if (txt) clouds[a as Speaker] = { text: txt, own: a === current.speaker ? current.ownThought : undefined };
    }
  }
  if (working) for (const a of working.agents) clouds[a as Speaker] = { text: working.doing, working: true };

  // Facts by id, so a turn's citations can be highlighted in the document.
  const facts = useMemo(() => {
    const out: Record<string, { quote: string | null; page: number | null }> = {};
    for (const e of log) if (e.type === "fact.extracted") out[e.payload.id] = { quote: e.payload.quote, page: e.payload.page };
    return out;
  }, [log]);
  const cited = useMemo(() => {
    const c = current?.card;
    const ids = c && (c.kind === "argument" || c.kind === "challenge" || c.kind === "rebuttal") ? c.facts : [];
    const quotes = ids.map((f) => facts[f]?.quote).filter((q): q is string => Boolean(q));
    if (current?.quote) quotes.push(current.quote);
    return { pages: current?.pages ?? [], quotes };
  }, [current, facts]);

  async function raiseHand(e: React.FormEvent) {
    e.preventDefault();
    speech.current?.unlock();
    const text = draft.trim();
    if (!text) return;
    const r = await fetch(`/api/runs/${id}/notes`, { method: "POST", headers: { "content-type": "application/json" },
                                                     body: JSON.stringify({ text, afterSeq: upTo }) }).then((x) => x.json()).catch(() => null);
    if (r?.note) setNotes((n) => [...n, r.note]);
    setDraft(""); setHand(false);
    const reply = "Noted. That goes on the record for the reviewer. Let's continue.";
    setAck(reply);
    say("moderator", reply, () => { setAck(null); setPlaying(true); });
  }

  // Transcript: spoken lines so far, with your notes placed where you raised your hand.
  const all: ({ t: "line"; l: Line; i: number } | { t: "note"; n: Note })[] = lines.slice(0, shown).map((l, i) => ({ t: "line" as const, l, i }));
  notes.forEach((n) => {
    const at = all.reduce((pos, it, k) => (it.t === "line" && it.l.upTo <= n.afterSeq ? k + 1 : pos), 0);
    if (at > 0 || shown > 0) all.splice(at, 0, { t: "note", n });
  });
  const merged = focus ? all.filter((it) => (it.t === "line" ? it.l.speaker === focus : focus === "you")) : all;

  const status = idx < 0 ? <>Take your seat and press <b>Start</b>. {voices.length ? "Turn your sound on." : ""}</>
    : phase === "think" && speaking ? <><b>{SEAT[speaking].name}</b> is thinking…</>
    : speaking ? <><b>{SEAT[speaking].name}</b> is speaking{current?.to ? <> to <b>{current.to}</b></> : null}</>
    : working ? <>The council is working: {working.doing.toLowerCase()}… new turns appear as they are made.</>
    : atGate ? <>The council has decided. <b>Your turn:</b> approve or override.</>
    : playing ? "…" : "Paused.";

  return (
    <PhotosCtx.Provider value={photoSet}>
      <div className="topicbar">
        <div className="tb-round">
          <span className="mono">{working?.round ?? round ?? "—"}</span>
          <strong>{ROUND_TITLES[(working?.round ?? round ?? "R0") as Round]}</strong>
        </div>
        <div className="tb-topic">
          <span className="muted">Topic</span>
          <strong>{topic ? names[topic] ?? topic : round === "R0" ? "Reading the document" : round === "R1" ? "Which frameworks apply" : "—"}</strong>
        </div>
        <div className="tb-progress">
          {ROUNDS.map((r) => {
            const done = round !== null && ROUNDS.indexOf(r) < ROUNDS.indexOf(round);
            return <span key={r} className={`pip ${round === r ? "now" : done ? "done" : ""}`} title={ROUND_TITLES[r]}>{r}</span>;
          })}
        </div>
        <div className="tb-actions">
          {running && <span className="chip warn">● live</span>}
          {decided && <Link className="btn primary" href={`/runs/${id}/output`}>Final output →</Link>}
        </div>
      </div>

      <div className="room3">
        <DocumentPanel doc={doc} pages={cited.pages} quotes={cited.quotes} />

        <section className="arena">
          <div className={`tablestage ${focus && focus !== "you" ? "has-focus" : ""}`}>
            {SEATS.map((s) => (
              <div key={s.id} className={`seat2 seat-${s.id} ${speaking === s.id ? (phase === "think" ? "thinking" : "speaking") : ""} ${clouds[s.id]?.working ? "busy" : ""} ${focus === s.id || (s.id === "you" && hand) ? "focused" : ""}`}
                   style={{ ["--who" as string]: s.color }} role="button" tabIndex={0}
                   title={s.id === "you" ? "Raise your hand (H)" : `${s.name}: profile and turns`}
                   onClick={() => clickSeat(s.id)} onKeyDown={(e) => { if (e.key === "Enter") clickSeat(s.id); }}>
                {clouds[s.id] && <Cloud {...clouds[s.id]!} />}
                {burst?.who === s.id && <span key={burst.n} className="burst" aria-hidden="true">{burst.emoji}</span>}
                {s.id === "you" && hand && <span className="burst hand" aria-hidden="true">✋</span>}
                <Face id={s.id} speaking={speaking === s.id && phase === "speak"} />
                <div className="nm" style={{ color: s.color }}>{s.name}</div>
                <div className="rl">{s.role}</div>
                {team[s.id] && (
                  <div title={`Set to ${team[s.id].main}${team[s.id].fellBack ? "; fell back to this model" : ""}`}
                       style={{ font: "500 10.5px var(--f-mono)", color: team[s.id].working ? "var(--accent)" : "var(--muted)",
                                lineHeight: 1.3, maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {team[s.id].working ? "● " : ""}{team[s.id].model}
                    <span style={{ display: "block", fontSize: 9.5 }}>
                      {team[s.id].provider}{team[s.id].fellBack ? " · fallback" : ""}{!team[s.id].used ? " · not called yet" : ""}
                    </span>
                  </div>
                )}
              </div>
            ))}
            <div className="tabletop">
              {current?.card ? <OnTable card={current.card} names={names} key={current.key} />
                : <p className="empty" style={{ textAlign: "center" }}>
                    {working ? `${working.doing}…` : "The evidence for what is being said lands here."}</p>}
            </div>
          </div>

          <div className="caption" aria-live="polite">
            {current ? (
              <>
                <span className="caption-face"><Face id={current.speaker} speaking={speaking === current.speaker && phase === "speak"} /></span>
                <div>
                  <div className="who">{SEAT[current.speaker].name}{current.to && <span>→ {current.to}</span>}</div>
                  <p>{phase === "think" ? <span className="muted">…</span> : current.text}</p>
                </div>
                <div className="reacts" role="group" aria-label="React to this turn">
                  {REACTIONS.map((r, k) => (
                    <button key={r} className={reactions[current.key] === r ? "on" : ""} onClick={() => react(r)} title={`React (${k + 1})`}>{r}</button>
                  ))}
                </div>
              </>
            ) : <p className="muted">{status}</p>}
          </div>

          <div className="panel controls-panel">
            {lines.length > 0 && <Timeline lines={lines} idx={idx} focus={focus} reactions={reactions} onJump={jump} />}
            <div className="room-status">{status}</div>
            <div className="controls-row">
              <button onClick={back} disabled={idx <= 0} title="Previous turn (←)">⏮</button>
              {playing ? <button onClick={pause} title="Pause (space)">❚❚ Pause</button>
                : <button className="primary" onClick={play} title="Play (space)">{idx < 0 ? "▶ Start" : idx >= lines.length && !running ? "↺ From the start" : "▶ Continue"}</button>}
              <button onClick={skip} disabled={idx < 0} title="Next turn (→)">Next turn ⏭</button>
              <button onClick={toEnd}>Skip to the end</button>
              <label className="toggle"><input type="checkbox" checked={voiceOn} onChange={(e) => { setVoiceOn(e.target.checked); if (!e.target.checked) stopVoice(); }} /> Voices</label>
              <select value={engine} onChange={(e) => { stopVoice(); setEngine(e.target.value as "edge" | "browser"); }} disabled={!voiceOn}
                      title="Neural: Microsoft Edge voices through edge-tts (text is sent to Microsoft). Browser: voices on this computer.">
                <option value="edge">Neural voices</option>
                <option value="browser">Browser voices</option>
              </select>
              <label className="toggle">Pace
                <input type="range" min={0.75} max={2} step={0.25} value={speed} onChange={(e) => setSpeed(Number(e.target.value))} />
              </label>
              <button className={hand ? "on" : ""} onClick={() => { pause(); setHand(!hand); }}>✋ Raise your hand</button>
              <span className="muted mono" style={{ marginLeft: "auto" }}>turn {Math.max(0, shown)}/{lines.length}{running ? "+" : ""}</span>
            </div>
            <div className="kbd-hint muted">
              <kbd>Space</kbd> play/pause · <kbd>←</kbd><kbd>→</kbd> turns · <kbd>1</kbd>–<kbd>4</kbd> react · <kbd>H</kbd> raise hand · click a person to follow them
            </div>
            {hand && (
              <form className="composer" onSubmit={raiseHand}>
                <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)}
                       placeholder="Say something to the council: a question, a concern, a fact they missed…" />
                <button className="primary" type="submit">Say it</button>
              </form>
            )}
          </div>
        </section>

        <aside className="side">
          {(atGate || signed) && <Gate id={id} signed={signed?.payload} decision={decision} names={names} onSigned={(ev) => setLog((l) => [...l, ev])} />}
          {focus && focus !== "you" && (
            <Profile who={focus} intro={intros.find((x) => x.agent === focus)} model={team[focus]} lines={lines} idx={idx} shown={shown}
                     names={names} onJump={jump} onClose={() => setFocus(null)} key={focus} />
          )}
          <div className="panel">
            <div className="tabs">
              <button className={tab === "talk" ? "on" : ""} onClick={() => setTab("talk")}>Conversation</button>
              <button className={tab === "stand" ? "on" : ""} onClick={() => setTab("stand")}>Where things stand</button>
              <Link href={`/runs/${id}`} className="muted" style={{ marginLeft: "auto", fontSize: 13 }}>board view</Link>
            </div>
            {tab === "talk" && (
              <div className="who-filter" role="group" aria-label="Show turns by">
                <button className={!focus ? "on" : ""} onClick={() => setFocus(null)}>Everyone</button>
                {SEATS.map((s) => (
                  <button key={s.id} className={focus === s.id ? "on" : ""} onClick={() => setFocus(focus === s.id ? null : s.id)} title={`Only ${s.name}`}>
                    <span className="avatar" style={{ background: s.color }}>{s.name[0]}</span>{s.name}
                  </button>
                ))}
              </div>
            )}
            {tab === "talk" ? (
              <div className="transcript" ref={transcript}>
                {merged.length === 0 && <p className="empty">{focus ? `Nothing from ${SEAT[focus].name} yet.` : "The conversation appears here as each member speaks."}</p>}
                {merged.map((it) => it.t === "line" ? (
                  <div key={it.l.key} className={`msg jump ${it.l === current ? "now" : ""}`} role="button" tabIndex={0} title="Go to this turn"
                       onClick={() => jump(it.i)} onKeyDown={(e) => { if (e.key === "Enter") jump(it.i); }}>
                    <span className="avatar" style={{ background: SEAT[it.l.speaker].color }}>{SEAT[it.l.speaker].name[0]}</span>
                    <div>
                      <div className="who">{SEAT[it.l.speaker].name}{it.l.to && <span>→ {it.l.to}</span>}<span>{ROUND_TITLES[it.l.round]}</span>
                        {reactions[it.l.key] && <b className="react">{reactions[it.l.key]}</b>}</div>
                      {it.l.ownThought && it.l.thoughts?.[it.l.speaker] && <p className="thought-line">💭 {it.l.thoughts[it.l.speaker]}</p>}
                      <p>{it.l.text}</p>
                    </div>
                  </div>
                ) : (
                  <div key={`n${it.n.at}`} className="msg you">
                    <span className="avatar" style={{ background: "var(--accent)" }}>Y</span>
                    <div><div className="who">You<span>on the record</span></div><p>{it.n.text}</p></div>
                  </div>
                ))}
                {ack && (
                  <div className="msg"><span className="avatar" style={{ background: "var(--c-mod)" }}>M</span>
                    <div><div className="who">Mira</div><p>{ack}</p></div></div>
                )}
              </div>
            ) : <Scoreboard lines={lines.slice(0, shown)} names={names} />}
          </div>
        </aside>
      </div>
    </PhotosCtx.Provider>
  );
}

/* ---------- timeline: every turn as a bar in the speaker's colour; hover to preview, click to go there ---------- */
function Timeline({ lines, idx, focus, reactions, onJump }: {
  lines: Line[]; idx: number; focus: Speaker | null; reactions: Record<string, string>; onJump: (i: number) => void;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const h = hover !== null ? lines[hover] : undefined;
  return (
    <div className="timeline" onMouseLeave={() => setHover(null)}>
      <div className="tl-track">
        {lines.map((l, i) => (
          <button key={l.key} tabIndex={-1} aria-label={`Turn ${i + 1}: ${SEAT[l.speaker].name}`}
                  className={`tl-seg ${i < idx ? "played" : ""} ${i === idx ? "now" : ""} ${focus && l.speaker !== focus ? "dim" : ""} ${i > 0 && lines[i - 1].round !== l.round ? "new-round" : ""}`}
                  style={{ ["--who" as string]: SEAT[l.speaker].color }}
                  onMouseEnter={() => setHover(i)} onClick={() => onJump(i)}>
            {reactions[l.key] && <span className="tl-r">{reactions[l.key]}</span>}
          </button>
        ))}
      </div>
      {h && hover !== null && (
        <div className="tl-tip" style={{ left: `clamp(130px, ${((hover + 0.5) / lines.length) * 100}%, calc(100% - 130px))` }}>
          <b style={{ color: SEAT[h.speaker].color }}>{SEAT[h.speaker].name}</b> <span className="mono">{h.round} · turn {hover + 1}</span>
          <p>{h.text.length > 140 ? `${h.text.slice(0, 140)}…` : h.text}</p>
        </div>
      )}
    </div>
  );
}

/* ---------- profile of the person you clicked: who they are, where they stand, their turns ---------- */
function Profile({ who, intro, model, lines, idx, shown, names, onJump, onClose }: {
  who: Speaker; intro?: Intro; model?: SeatModel; lines: Line[]; idx: number; shown: number; names: Record<string, string>;
  onJump: (i: number) => void; onClose: () => void;
}) {
  const s = SEAT[who];
  const theirs = lines.map((l, i) => (l.speaker === who ? i : -1)).filter((i) => i >= 0);
  const spoken = theirs.filter((i) => i < shown).length;
  const prev = [...theirs].reverse().find((i) => i < idx);
  const next = theirs.find((i) => i > idx);
  // Their latest position on each subject, from what has been said so far.
  const stances: Record<string, string> = {};
  for (const l of lines.slice(0, shown)) {
    const c = l.card;
    if (c?.kind === "argument" && c.agent === who) stances[c.subject] = c.stance;
    if (c?.kind === "votes") for (const v of c.votes) if (v.agent === who) stances[c.subject] = v.stance;
  }
  return (
    <div className="panel profile" style={{ ["--who" as string]: s.color }}>
      <div className="profile-head">
        <Face id={who} speaking={false} />
        <div><div className="nm">{s.name}</div><div className="rl">{intro?.role ?? s.role}{intro ? ` · ${intro.votes ? "votes" : "does not vote"}` : ""}</div></div>
        <button className="x" onClick={onClose} aria-label="Close" title="Close (Esc)">×</button>
      </div>
      <dl>
        {intro?.specialty && <><dt>Specialty</dt><dd>{intro.specialty}</dd></>}
        {intro?.works_on && <><dt>Works on</dt><dd>{intro.works_on}</dd></>}
        {model && <><dt>LLM</dt><dd className="mono">{model.model} <span className="muted">· {model.provider}{model.fellBack ? " · fallback" : ""}</span></dd></>}
        <dt>Turns</dt><dd>{spoken} so far{theirs.length > spoken ? ` · ${theirs.length - spoken} to come` : ""}</dd>
      </dl>
      {Object.keys(stances).length > 0 && (
        <div className="stances">
          {Object.entries(stances).map(([subj, st]) => (
            <span key={subj} className={`chip ${STANCE_CHIP[st] ?? ""}`} title={STANCE[st]}>{names[subj] ?? subj}: {STANCE[st]}</span>
          ))}
        </div>
      )}
      <div className="nav">
        <button onClick={() => prev !== undefined && onJump(prev)} disabled={prev === undefined}>◀ Their previous turn</button>
        <button onClick={() => next !== undefined && onJump(next)} disabled={next === undefined}>Their next turn ▶</button>
      </div>
    </div>
  );
}

/* ---------- the document, section by section, following what is being cited ---------- */
function DocumentPanel({ doc, pages, quotes }: { doc: Doc | null; pages: number[]; quotes: string[] }) {
  const [picked, setPicked] = useState<number | null>(null);
  const followed = pages[0] ?? null;
  useEffect(() => { setPicked(null); }, [followed]);        // a new citation takes over from your own pick
  const open = picked ?? followed ?? doc?.sections[0]?.number ?? null;
  const section = doc?.sections.find((s) => s.number === open);
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => { body.current?.querySelector("mark")?.scrollIntoView({ block: "center", behavior: "smooth" }); }, [open, quotes.join("|")]);

  if (!doc) {
    return (
      <aside className="docpane panel">
        <h3>Document</h3>
        <p className="empty">The document outline appears here once the council starts reading. (Sessions run before this version did not save it.)</p>
      </aside>
    );
  }
  return (
    <aside className="docpane panel">
      <h3 title={doc.name}>{doc.name}</h3>
      <ol className="outline">
        {doc.sections.map((s) => (
          <li key={s.number}>
            <button className={`${s.number === open ? "on" : ""} ${pages.includes(s.number) ? "cited" : ""}`} onClick={() => setPicked(s.number)}>
              <span className="mono">{s.number}</span> {s.title ?? `Section ${s.number}`}
            </button>
          </li>
        ))}
      </ol>
      {section && (
        <div className="doctext" ref={body}>
          {section.text.split("\n").map((ln, k) => {
            const h = /^#{1,6}\s+(.*)$/.exec(ln);
            return h ? <strong key={k} className="dh">{h[1]}</strong> : <p key={k}>{highlight(ln, quotes)}</p>;
          })}
        </div>
      )}
    </aside>
  );
}

/** Wrap every quoted passage in <mark> (case-insensitive, ignoring markdown symbols around it). */
function highlight(text: string, quotes: string[]): React.ReactNode {
  const clean = text.replace(/[*_`]/g, "");
  const lower = clean.toLowerCase();
  const spans: [number, number][] = [];
  for (const q of quotes) {
    const needle = q.replace(/[*_`]/g, "").replace(/[.;:"'“”]+$/, "").toLowerCase().trim();
    if (needle.length < 6) continue;
    const at = lower.indexOf(needle);
    if (at >= 0) spans.push([at, at + needle.length]);
  }
  if (!spans.length) return clean || " ";
  spans.sort((a, b) => a[0] - b[0]);
  const out: React.ReactNode[] = [];
  let pos = 0;
  spans.forEach(([a, b], k) => {
    if (a < pos) return;
    out.push(clean.slice(pos, a), <mark key={k}>{clean.slice(a, b)}</mark>);
    pos = b;
  });
  out.push(clean.slice(pos));
  return out;
}

/* ---------- the card on the table ---------- */
function OnTable({ card, names }: { card: TableCard; names: Record<string, string> }) {
  const nm = (s: string) => names[s] ?? s;
  switch (card.kind) {
    case "fact":
      return (
        <div className="tcard">
          <div className="k">Fact {card.id}</div>
          <span className={`stamp ${card.status === "confirmed" ? "v-verified" : "v-partly_supports"}`}>{card.status}</span>
          <div className="big-line">{card.label}: <strong>{card.value}</strong></div>
          {card.quote ? <blockquote>“{card.quote}”<span className="src">product document, page {card.page}</span></blockquote>
            : <p className="muted">{card.note}</p>}
        </div>
      );
    case "shortlist":
      return (
        <div className="tcard">
          <div className="k">Which frameworks apply</div>
          <div className="shortlist">{card.items.map((i) => (
            <span key={i.id} className={`chip ${i.status === "binding" ? "accent" : i.status === "candidate" ? "good" : i.status === "needs_fact" ? "warn" : "na"}`} title={i.reason}>{i.name}</span>
          ))}</div>
        </div>
      );
    case "argument":
      return (
        <div className="tcard" style={{ ["--who" as string]: SEAT[card.agent as Speaker]?.color }}>
          <div className="k">{SEAT[card.agent as Speaker]?.name}'s argument · {nm(card.subject)}</div>
          <span className={`stamp stance-${card.stance}`}>{STANCE[card.stance]}</span>
          <p className="big-line">{card.claim}</p>
          {card.condition && <p className="muted">Condition: {card.condition}</p>}
          <div className="refs">Cites {card.facts.join(", ") || "no facts"}</div>
          {card.issues.length > 0 && <div className="chip warn">{card.issues.join("; ")}</div>}
        </div>
      );
    case "check":
      return (
        <div className="tcard" style={{ ["--who" as string]: "var(--c-fact)" }}>
          <div className="k">Vera checks · {nm(card.subject)}</div>
          <table><tbody>{card.rows.map((r) => (
            <tr key={r.agent}><td><strong>{SEAT[r.agent as Speaker]?.name}</strong></td>
              <td>{r.marks.map((m) => <span key={m.ref} className={`mark v-${m.verdict}`} title={m.note ?? m.verdict}>{m.ref} {m.verdict === "verified" ? "✓" : m.verdict === "contradicted" ? "✗" : m.verdict === "partly_supports" ? "½" : "?"}</span>)}</td>
              <td className="mono">weight {r.weight}</td></tr>
          ))}</tbody></table>
        </div>
      );
    case "challenge":
      return (
        <div className="tcard challenge-card" style={{ ["--who" as string]: SEAT[card.agent as Speaker]?.color }}>
          <div className="k">{card.counter ? "Counter-case to the whole panel" : `Challenge to ${card.target}`} · {nm(card.subject)}</div>
          <span className="stamp v-contradicted">{card.type}</span>
          <p className="big-line">{card.text}</p>
          <div className="refs">Cites {card.facts.join(", ") || "nothing"} · evidence weight {card.weight ?? "…"}</div>
        </div>
      );
    case "rebuttal":
      return (
        <div className={`tcard ${card.response === "concede" ? "conceded" : ""}`} style={{ ["--who" as string]: SEAT[card.agent as Speaker]?.color }}>
          <div className="k">{card.response === "concede" ? "Concedes" : "Rebuts"} · {nm(card.subject)}</div>
          <span className={`stamp ${card.response === "concede" ? "v-unverified" : (card.weight ?? 0) > 0 ? "v-verified" : "v-partly_supports"}`}>
            {card.response === "concede" ? "card withdrawn" : (card.weight ?? 0) > 0 ? "answered" : "no evidence"}</span>
          <p className="big-line">{card.text}</p>
          {card.response === "rebut" && <div className="refs">Cites {card.facts.join(", ") || "nothing"} · weight {card.weight ?? 0}</div>}
        </div>
      );
    case "votes":
      return (
        <div className="tcard">
          <div className="k">{card.revote ? "Re-vote" : "Blind vote"} · {nm(card.subject)}</div>
          {card.compromise && <p className="muted">Compromise: {card.compromise}</p>}
          <div className="vote-grid">{card.votes.map((v) => (
            <div key={v.agent} className="vote-tile" style={{ ["--who" as string]: SEAT[v.agent as Speaker]?.color }}>
              <strong>{SEAT[v.agent as Speaker]?.name}</strong>
              <span className={`stance ${v.stance}`}>{STANCE[v.stance]}</span>
              <span className="mono">confidence {v.confidence}/5</span>
            </div>
          ))}</div>
        </div>
      );
    case "result": {
      const a = card.agreement ?? 0;
      return (
        <div className="tcard">
          <div className="k">Result · {nm(card.subject)}</div>
          <div className={`banner o-${card.outcome}`}>{OUTCOME[card.outcome] ?? card.outcome}{card.agreement !== null && <span> {Math.round(a)}%</span>}</div>
          <div className="meter" style={{ ["--fill" as string]: a >= 60 ? "var(--good)" : a >= 40 ? "var(--warn)" : "var(--bad)" }}>
            <span style={{ width: `${a}%` }} />{[40, 60, 75].map((t) => <i key={t} className="tick" style={{ left: `${t}%` }} />)}
          </div>
          {card.v !== null && <p className="mono muted">vote {card.v}% · evidence {card.e}% · agreement = 0.6 × vote + 0.4 × evidence</p>}
          {card.guardrail && <p>Condition: {card.guardrail}</p>}
          {!card.guardrail && <p className="muted">{card.reason}</p>}
        </div>
      );
    }
    case "statement":
      return (
        <div className="tcard">
          <div className="k">Position statement · stage agreement {card.agreement !== null ? `${Math.round(card.agreement)}%` : "—"}</div>
          <p className="statement">{card.text}</p>
        </div>
      );
    case "signed":
      return <div className="tcard"><div className="k">Reviewer</div><div className={`banner ${card.decision === "approve" ? "o-selected" : "o-reviewer_decides"}`}>{card.decision === "approve" ? "Approved" : "Overridden"}</div><p>{card.reason}</p></div>;
    case "error":
      return <div className="tcard"><div className="k">Missed turn</div><p className="muted">{card.text}</p></div>;
    case "intro": {
      const [main, ...backups] = card.models;
      return (
        <div className="tcard" style={{ ["--who" as string]: SEAT[card.agent as Speaker]?.color }}>
          <div className="k">Meet the council · {card.votes ? "votes" : "does not vote"}</div>
          <div className="big-line"><strong>{card.name}</strong>, {card.role}</div>
          <p style={{ margin: "4px 0" }}><span className="muted">Specialised in </span>{card.specialty}</p>
          <p style={{ margin: "4px 0" }}><span className="muted">Works on </span>{card.worksOn}</p>
          {main && (
            <p className="refs" style={{ margin: "6px 0 0" }}>
              LLM: {sayModel(main)}{backups.length ? <> · backup {backups.map(sayModel).join(", then ")}</> : null}
            </p>
          )}
        </div>
      );
    }
  }
}

/* ---------- running scoreboard: where each subject stands so far ---------- */
function Scoreboard({ lines, names }: { lines: Line[]; names: Record<string, string> }) {
  const rows = new Map<string, { stances: Record<string, string>; outcome?: string; agreement?: number | null }>();
  for (const l of lines) {
    const c = l.card;
    if (!c) continue;
    if (c.kind === "argument") {
      const r = rows.get(c.subject) ?? { stances: {} };
      r.stances[c.agent] = c.stance; rows.set(c.subject, r);
    } else if (c.kind === "votes") {
      const r = rows.get(c.subject) ?? { stances: {} };
      c.votes.forEach((v) => { r.stances[v.agent] = v.stance; }); rows.set(c.subject, r);
    } else if (c.kind === "result") {
      const r = rows.get(c.subject) ?? { stances: {} };
      r.outcome = c.outcome; r.agreement = c.agreement; rows.set(c.subject, r);
    }
  }
  if (rows.size === 0) return null;
  return (
    <div className="panel">
      <h3 style={{ marginBottom: 4 }}>Where things stand</h3>
      <p className="muted" style={{ fontSize: 12, margin: "0 0 8px" }}>
        Each voter's latest position: <span className="sdot sd-adopt">T</span> adopt <span className="sdot sd-adopt_with_condition">T</span> conditional <span className="sdot sd-reject">T</span> reject
      </p>
      <table className="score"><tbody>
        {[...rows.entries()].map(([s, r]) => (
          <tr key={s}>
            <td>{names[s] ?? s}</td>
            <td>{(["strategist", "architect", "platform_cost", "critic"] as Speaker[]).map((a) => r.stances[a] && (
              <span key={a} className={`sdot sd-${r.stances[a]}`} title={`${SEAT[a].name}: ${STANCE[r.stances[a]]}`}>{SEAT[a].name[0]}</span>
            ))}</td>
            <td className={`o-${r.outcome ?? ""}`} style={{ fontSize: 12.5, fontWeight: 600 }}>
              {r.outcome ? `${OUTCOME[r.outcome] ?? r.outcome}${r.agreement !== null && r.agreement !== undefined ? ` · ${Math.round(r.agreement)}%` : ""}` : ""}
            </td>
          </tr>
        ))}
      </tbody></table>
    </div>
  );
}

/* ---------- the reviewer gate: your seat ---------- */
function Gate({ id, signed, decision, names, onSigned }: {
  id: string; signed?: Record<string, any>; decision: Decision | null; names: Record<string, string>; onSigned: (ev: CouncilEvent) => void;
}) {
  const [reason, setReason] = useStored(`room:${id}:reason`, "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (signed) {
    return (
      <div className="panel gate">
        <h3>Reviewer sign-off</h3>
        <p>{signed.decision === "approve" ? "Approved" : "Overridden"}{signed.auto ? " automatically (run with --review approve)" : signed.by === "room" ? " by you, in the room" : ""}.
          {signed.reason ? ` ${signed.reason}` : ""}</p>
      </div>
    );
  }
  const open = (decision?.board ?? []).filter((r) => r.outcome === "reviewer_decides" || r.outcome === "parked");
  async function sign(d: "approve" | "override") {
    setBusy(true); setError(null);
    const r = await fetch(`/api/runs/${id}/review`, { method: "POST", headers: { "content-type": "application/json" },
                                                    body: JSON.stringify({ decision: d, reason }) }).then((x) => x.json()).catch(() => ({ error: "network" }));
    setBusy(false);
    if (r.error) setError(r.error); else onSigned(r.event);
  }
  return (
    <div className="panel gate">
      <h3>Your decision</h3>
      <p>The council has signed its position. You have the last word: approve it, or override with a reason that goes on the record next to their numbers.</p>
      {open.length > 0 && <p className="muted">Left for you: {open.map((r) => names[r.subject] ?? r.subject).join(", ")}.</p>}
      <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3}
                placeholder="Your reason (needed to override; optional to approve). E.g. adopt ADR, reject ATAM for the pilot…" />
      <div className="controls-row">
        <button className="primary" disabled={busy} onClick={() => sign("approve")}>Approve</button>
        <button disabled={busy || !reason.trim()} onClick={() => sign("override")}>Override with my reason</button>
        {error && <span className="chip bad">{error}</span>}
      </div>
    </div>
  );
}
