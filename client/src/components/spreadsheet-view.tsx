import { useState, useEffect, useRef } from "react";
import { LoadingBar } from "./loading-bar";

interface Sheet { html: string; rowsTrunc: boolean; colsTrunc: boolean }

// Renders csv/xlsx/xls/ods via SheetJS, parsed in a Web Worker. `url` is an
// authed blob URL (from openFile), so this works for both owned files and
// token-scoped shares. The worker parse-caps rows (huge-file guard) and we
// render one sheet at a time, on demand.
export function SpreadsheetView({ url, name }: { url: string; name: string }) {
  // Excel/ODS render as values only (no formatting/formulas/charts) → always a
  // preview. CSV has no formatting, so its table is complete unless truncated.
  const excel = /\.(xlsx|xls|ods)$/i.test(name);
  const [names, setNames] = useState<string[] | null>(null);
  const [rtl, setRtl] = useState(false);
  const [active, setActive] = useState(0);
  const [sheets, setSheets] = useState<Record<number, Sheet>>({});
  const [error, setError] = useState(false);
  const workerRef = useRef<Worker | null>(null);

  useEffect(() => {
    let cancelled = false;
    setNames(null); setSheets({}); setActive(0); setRtl(false); setError(false);
    const worker = new Worker(new URL("../lib/xlsx-worker.ts", import.meta.url), { type: "module" });
    workerRef.current = worker;
    worker.onmessage = (e: MessageEvent) => {
      if (cancelled) return;
      const d = e.data;
      if (d.type === "init") {
        setNames(d.sheetNames);
        setRtl(d.rtl);
        worker.postMessage({ sheet: 0 });   // eagerly fetch the first sheet only
      } else if (d.type === "sheet") {
        setSheets((prev) => ({ ...prev, [d.index]: { html: d.html, rowsTrunc: d.rowsTrunc, colsTrunc: d.colsTrunc } }));
      } else if (d.type === "error") {
        setError(true);
      }
    };
    worker.onerror = () => { if (!cancelled) setError(true); };
    (async () => {
      try {
        const buffer = await (await fetch(url)).arrayBuffer();
        if (!cancelled) worker.postMessage({ buffer }, [buffer]);   // transfer — zero-copy
      } catch {
        if (!cancelled) setError(true);
      }
    })();
    return () => { cancelled = true; worker.terminate(); workerRef.current = null; };
  }, [url]);

  const selectSheet = (i: number) => {
    setActive(i);
    if (!sheets[i]) workerRef.current?.postMessage({ sheet: i });
  };

  if (error) {
    return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Couldn't render this spreadsheet.</div>;
  }
  if (!names) return <LoadingBar />;
  if (!names.length) {
    return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Empty spreadsheet.</div>;
  }

  const cur = sheets[active];
  const trunc = !!cur && (cur.rowsTrunc || cur.colsTrunc);

  return (
    <div className="flex h-full flex-col" dir={rtl ? "rtl" : "ltr"}>
      {names.length > 1 && (
        <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-border px-2 py-1.5">
          {names.map((s, i) => (
            <button
              key={s + i}
              onClick={() => selectSheet(i)}
              className={`shrink-0 rounded-md px-2.5 py-1 text-xs transition-colors cursor-pointer ${i === active ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/60"}`}
            >
              {s}
            </button>
          ))}
        </div>
      )}
      <div className="flex-1 overflow-auto">
        {cur ? (
          <div
            className="w-max min-w-full text-sm [&_table]:border-collapse [&_td]:whitespace-nowrap [&_td]:border [&_td]:border-border [&_td]:px-2.5 [&_td]:py-1 [&_th]:border [&_th]:border-border [&_th]:bg-secondary [&_th]:px-2.5 [&_th]:py-1 [&_tr:nth-child(even)_td]:bg-secondary/30"
            dangerouslySetInnerHTML={{ __html: cur.html }}
          />
        ) : (
          <LoadingBar />
        )}
      </div>
      {cur && (trunc || excel) && (
        <div className="shrink-0 border-t border-border px-3 py-1.5 text-xs text-muted-foreground">
          {trunc
            ? <>Large file — preview limited to the first {cur.rowsTrunc ? "300 rows" : ""}{cur.rowsTrunc && cur.colsTrunc ? " and " : ""}{cur.colsTrunc ? "50 columns" : ""}. Download to open the full file.</>
            : "Preview only — values shown without formatting. Download to open the full file."}
        </div>
      )}
    </div>
  );
}
