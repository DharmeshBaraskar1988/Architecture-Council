import { existsSync, promises as fs } from "fs";
import path from "path";
import { NextResponse } from "next/server";
import { CLIPS_DIR } from "@/lib/avatars";

// One talking-head video (silent MP4). Supports byte ranges, which browsers use to play and seek video.
export async function GET(req: Request, { params }: { params: Promise<{ clip: string }> }) {
  const { clip } = await params;
  if (!/^[0-9a-f]{40}$/.test(clip)) return NextResponse.json({ error: "bad clip id" }, { status: 400 });
  const file = path.join(/*turbopackIgnore: true*/ CLIPS_DIR, `${clip}.mp4`);
  if (!existsSync(file)) return NextResponse.json({ error: "not rendered yet" }, { status: 404 });
  const data = await fs.readFile(file);
  const headers = { "content-type": "video/mp4", "accept-ranges": "bytes", "cache-control": "private, max-age=604800, immutable" };
  const m = /bytes=(\d*)-(\d*)/.exec(req.headers.get("range") ?? "");
  if (!m) return new NextResponse(new Uint8Array(data), { headers: { ...headers, "content-length": String(data.length) } });
  const start = m[1] ? Number(m[1]) : Math.max(0, data.length - Number(m[2]));
  const end = m[1] && m[2] ? Math.min(Number(m[2]), data.length - 1) : data.length - 1;
  if (start >= data.length || start > end) return new NextResponse(null, { status: 416, headers: { "content-range": `bytes */${data.length}` } });
  return new NextResponse(new Uint8Array(data.subarray(start, end + 1)), {
    status: 206, headers: { ...headers, "content-range": `bytes ${start}-${end}/${data.length}`, "content-length": String(end - start + 1) },
  });
}
