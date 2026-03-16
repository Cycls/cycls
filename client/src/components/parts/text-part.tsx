import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { memo, useState } from "react";
import { CodeBlock, CodeBlockCode, CodeBlockGroup } from "./code-block";

function escapeCurrencyDollars(text: string): string {
  return text.replace(/\$\$|\$\d[^$\n]{0,3}\$|\$(?=\d)/g, (m) =>
    m.length > 1 ? m : "\\$",
  );
}

export const TextPart = memo(function TextPart({ text }: { text: string }) {
  return (
    <div dir="auto" className="prose dark:prose-invert min-w-full">
      <ReactMarkdown
        remarkPlugins={[[remarkGfm, { singleTilde: false }], remarkMath]}
        rehypePlugins={[[rehypeKatex, { strict: false }]]}
        components={{
          code({ className, children }) {
            const match = /language-(\w+)/.exec(className || "");
            const code = String(children).replace(/\n$/, "");

            if (match || code.includes("\n")) {
              return <MarkdownCodeBlock code={code} language={match?.[1] || "text"} />;
            }

            return (
              <code className={className}>
                {children}
              </code>
            );
          },
          pre({ children }) {
            return <>{children}</>;
          },
        }}
      >
        {escapeCurrencyDollars(text)}
      </ReactMarkdown>
    </div>
  );
});

function MarkdownCodeBlock({
  code,
  language,
}: {
  code: string;
  language: string;
}) {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <CodeBlock className="my-3 bg-background">
      <CodeBlockGroup className="flex h-9 items-center justify-between px-4">
        <span className="font-mono text-xs text-muted-foreground">
          {language}
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
