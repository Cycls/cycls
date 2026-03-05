import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark, oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import { useState } from "react";
import { useDarkMode } from "../../hooks/use-dark-mode";

export function CodePart({
  code,
  language,
}: {
  code: string;
  language?: string;
}) {
  const isDark = useDarkMode();
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="my-3 overflow-clip rounded-xl border border-border bg-card">
      <div className="flex h-9 items-center justify-between px-4">
        <span className="font-mono text-xs text-muted-foreground">
          {language || "code"}
        </span>
        <button
          onClick={copy}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
        >
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
      <SyntaxHighlighter
        style={isDark ? oneDark : oneLight}
        language={language || "text"}
        PreTag="div"
        customStyle={{
          margin: 0,
          borderRadius: 0,
          fontSize: "14px",
          padding: "1rem",
        }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}
