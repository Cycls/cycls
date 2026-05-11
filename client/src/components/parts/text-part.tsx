import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { memo, useMemo } from "react";
import { unified } from "unified";
import remarkParse from "remark-parse";
import { CodePart } from "./code-part";

function escapeCurrencyDollars(text: string): string {
  return text.replace(/\$\$|\$(?=\d)(?![^$\n]*[\\^_{}][^$\n]*\$)/g, (m) =>
    m === "$$" ? m : "\\$",
  );
}

const parser = unified().use(remarkParse);

function parseMarkdownIntoBlocks(markdown: string): string[] {
  const tree = parser.parse(markdown);
  return tree.children.map((node) => {
    const start = node.position!.start.offset!;
    const end = node.position!.end.offset!;
    return markdown.slice(start, end);
  });
}

const markdownComponents = {
  code({ className, children }: { className?: string; children?: React.ReactNode }) {
    const match = /language-(\w+)/.exec(className || "");
    const code = String(children).replace(/\n$/, "");

    if (match || code.includes("\n")) {
      return <CodePart code={code} language={match?.[1] || "text"} className="bg-background" />;
    }

    return (
      <code className={className}>
        {children}
      </code>
    );
  },
  pre({ children }: { children?: React.ReactNode }) {
    return <>{children}</>;
  },
};

const remarkPlugins = [[remarkGfm, { singleTilde: false }], remarkMath] as const;
const rehypePlugins = [[rehypeKatex, { strict: false }]] as const;

const MemoizedMarkdownBlock = memo(
  function MarkdownBlock({ content }: { content: string }) {
    return (
      <ReactMarkdown
        remarkPlugins={remarkPlugins as any}
        rehypePlugins={rehypePlugins as any}
        components={markdownComponents as any}
      >
        {content}
      </ReactMarkdown>
    );
  },
  (prev, next) => prev.content === next.content,
);

export const TextPart = memo(function TextPart({ text }: { text: string }) {
  const escaped = escapeCurrencyDollars(text);
  const blocks = useMemo(() => parseMarkdownIntoBlocks(escaped), [escaped]);

  return (
    <div dir="auto" className="prose dark:prose-invert min-w-full">
      {blocks.map((block, index) => (
        <MemoizedMarkdownBlock key={index} content={block} />
      ))}
    </div>
  );
});
