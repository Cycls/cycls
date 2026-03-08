import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { memo, useState, useEffect } from "react";
import { CodeBlock, CodeBlockCode, CodeBlockGroup } from "./code-block";

let rehypeKatexPlugin: any = null;
const katexCdnUrl = "https://esm.sh/rehype-katex@7.0.1?deps=katex@0.16.33";
// @ts-ignore - CDN import
const rehypeKatexReady = import(/* @vite-ignore */ katexCdnUrl).then((m: any) => {
  rehypeKatexPlugin = m.default;
  // Load KaTeX CSS from CDN
  if (!document.querySelector('link[href*="katex"]')) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://esm.sh/katex@0.16.33/dist/katex.min.css";
    document.head.appendChild(link);
  }
});

export const TextPart = memo(function TextPart({ text }: { text: string }) {
  const [katexLoaded, setKatexLoaded] = useState(!!rehypeKatexPlugin);

  useEffect(() => {
    if (!rehypeKatexPlugin) {
      rehypeKatexReady.then(() => setKatexLoaded(true));
    }
  }, []);

  return (
    <div dir="auto" className="prose dark:prose-invert min-w-full">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={katexLoaded ? [rehypeKatexPlugin] : []}
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
        {text}
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
