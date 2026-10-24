import Link from "next/link";
import { notFound } from "next/navigation";
import { Markdown } from "@/lib/markdown";
import { readAdr, runDir } from "@/lib/runs";
import PrintButton from "./PrintButton";

export const dynamic = "force-dynamic";

// The final output of a session: the strategy decision document (ADR), signed or pending.
export default async function OutputPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!runDir(id)) notFound();
  const adr = await readAdr(id);
  return (
    <main className="wrap">
      <div className="topbar no-print">
        <Link href={`/runs/${id}/room`}>← Back to the room</Link>
        <h1>Final output</h1>
        <span className="mono muted">{id}</span>
      </div>
      {adr ? (
        <>
          <div className="output-actions no-print">
            <a className="btn primary" href={`/api/runs/${id}/output`}>Download (.md)</a>
            <PrintButton />
            <Link className="btn" href={`/runs/${id}/trace`}>Who is behind each decision</Link>
            {adr.includes("_Pending._") && <Link className="btn" href={`/runs/${id}/room?turn=end`}>Sign it in the room</Link>}
          </div>
          <article className="output"><Markdown source={adr} /></article>
        </>
      ) : (
        <p className="empty">No decision document yet: the council writes it at the end of round 7. Sessions run before this
          version did not write one; start a new session.</p>
      )}
    </main>
  );
}
