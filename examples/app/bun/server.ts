// A real Bun/TypeScript server. cycls handles deploy + multi-tenant
// workspace mounting; Bun handles the actual request work.
//
// `WORKSPACE` is a per-user directory the Python proxy stamps via the
// `X-Workspace` request header. Read/write here = per-tenant persistence
// (gcsfuse-backed in prod).

const port = parseInt(process.env.PORT || "3000");

interface Note {
  id: string;
  text: string;
  at: string;
}

function workspaceFor(req: Request): string {
  const ws = req.headers.get("x-workspace");
  if (!ws) throw new Error("X-Workspace header missing");
  return ws;
}

async function readNotes(ws: string): Promise<Note[]> {
  const file = Bun.file(`${ws}/notes.json`);
  if (!(await file.exists())) return [];
  return file.json();
}

async function writeNotes(ws: string, notes: Note[]): Promise<void> {
  await Bun.write(`${ws}/notes.json`, JSON.stringify(notes, null, 2));
}

const server = Bun.serve({
  port,
  async fetch(req) {
    const url = new URL(req.url);

    if (url.pathname === "/info") {
      return Response.json({
        runtime: "bun",
        version: Bun.version,
        platform: process.platform,
        arch: process.arch,
        pid: process.pid,
      });
    }

    if (url.pathname === "/notes" && req.method === "GET") {
      const ws = workspaceFor(req);
      return Response.json(await readNotes(ws));
    }

    if (url.pathname === "/notes" && req.method === "POST") {
      const ws = workspaceFor(req);
      const body = await req.json() as { text?: string };
      const notes = await readNotes(ws);
      const note: Note = {
        id: crypto.randomUUID().slice(0, 8),
        text: body.text || "",
        at: new Date().toISOString(),
      };
      notes.push(note);
      await writeNotes(ws, notes);
      return Response.json(note);
    }

    if (url.pathname === "/bench") {
      // Run a tiny CPU benchmark on Bun's V8: how many fibs in 100ms?
      const t0 = performance.now();
      let n = 0;
      const fib = (k: number): number => k < 2 ? k : fib(k - 1) + fib(k - 2);
      while (performance.now() - t0 < 100) { fib(20); n++; }
      return Response.json({ fibs_per_100ms: n, runtime: `bun ${Bun.version}` });
    }

    return new Response("not found", { status: 404 });
  },
});

console.log(`bun listening on :${server.port}`);
