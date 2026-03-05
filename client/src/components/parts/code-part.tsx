import { useState } from "react";
import { CodeBlock, CodeBlockCode, CodeBlockGroup } from "./code-block";

export function CodePart({
  code,
  language,
}: {
  code: string;
  language?: string;
}) {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <CodeBlock className="my-3">
      <CodeBlockGroup className="flex h-9 items-center justify-between px-4">
        <span className="font-mono text-xs text-muted-foreground">
          {language || "code"}
        </span>
        <button
          onClick={copy}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
        >
          {copied ? "Copied!" : "Copy"}
        </button>
      </CodeBlockGroup>
      <CodeBlockCode code={code} language={language} />
    </CodeBlock>
  );
}
