import { readAdr } from "@/lib/runs";

// Download the strategy ADR as Markdown.
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const adr = await readAdr(id);
  if (!adr) return new Response("No decision document yet: the council writes it at the end of R7.", { status: 404 });
  return new Response(adr, {
    headers: { "content-type": "text/markdown; charset=utf-8", "content-disposition": `attachment; filename="strategy-adr-${id}.md"` },
  });
}
