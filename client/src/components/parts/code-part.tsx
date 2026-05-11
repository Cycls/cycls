import { memo, useEffect, useState } from "react";
import { codeToHtml } from "shiki";
import { cn } from "../../lib/utils";
import { useDarkMode } from "../../hooks/use-dark-mode";

export const CodePart = memo(function CodePart({
  code,
  language,
  className,
}: {
  code: string;
  language?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={cn("not-prose my-3 flex w-full flex-col overflow-clip rounded-xl border border-border bg-card text-card-foreground", className)}>
      <div className="flex h-9 items-center justify-between px-4">
        <span className="font-mono text-xs text-muted-foreground">{language || "code"}</span>
        <button onClick={copy} className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer">
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
      <HighlightedCode code={code} language={language} />
    </div>
  );
});

function HighlightedCode({ code, language = "text" }: { code: string; language?: string }) {
  const isDark = useDarkMode();
  const [html, setHtml] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    codeToHtml(code, { lang: language, theme: isDark ? "github-dark" : "github-light" })
      .then((h) => { if (!cancelled) setHtml(h); })
      .catch(() => { if (!cancelled) setHtml(null); }); // unknown lang → plain text
    return () => { cancelled = true; };
  }, [code, language, isDark]);

  const cls = "w-full overflow-x-auto text-[14px] [&>pre]:px-4 [&>pre]:py-4 [&>pre]:!bg-background";
  return html
    ? <div className={cls} dangerouslySetInnerHTML={{ __html: html }} />
    : <div className={cls}><pre className="px-4 py-4"><code>{code}</code></pre></div>;
}
