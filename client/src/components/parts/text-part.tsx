import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { memo, useMemo } from "react";
import { unified } from "unified";
import remarkParse from "remark-parse";
import { CodePart } from "./code-part";
import { SourceChip, domainOf, urlKey } from "./sources-part";
import { track } from "../../lib/analytics";
import type { Source } from "../../hooks/use-chat";

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

const rehypePlugins = [[rehypeKatex, { strict: false }]] as const;

// A workspace file however the model wrote it — relative, /workspace/…,
// file://, sandbox:, or our own /files/ URL — as the path the canvas opens.
// Anything else is the web and gets null.
export function workspacePath(href: string): string | null {
  let h = href.replace(/^(file:\/\/|sandbox:)/i, "");
  if (/^https?:\/\//i.test(h)) {
    const u = new URL(h);
    if (u.origin !== location.origin || !u.pathname.startsWith("/files/")) return null;
    h = u.pathname.slice(7);
  } else if (/^([a-z][a-z0-9+.-]*:|\/\/|#)/i.test(h)) return null;
  h = decodeURI(h).replace(/^(\.\/|\/?workspace\/|\/)+/, "");
  return h || null;
}

// Bare paths in prose become links: "saved to reports/report.md".
const PATH = /(^|[\s(])((?:file:\/\/|sandbox:)?\/?(?:workspace\/|\.\/)?(?:[\w.-]+\/)*[\w-]+\.(?:md|html?|csv|tsv|json|txt|pdf|docx|xlsx|pptx|png|jpe?g|svg|gif))(?=[\s).,;:!?]|$)/g;
type Node = { type: string; value?: string; url?: string; children?: Node[] };
export function linkifyPaths(node: Node): Node {
  if (node.type === "text" && node.value) {
    const out: Node[] = []; let last = 0;
    for (const m of node.value.matchAll(PATH)) {
      const at = m.index! + m[1].length;
      if (at > last) out.push({ type: "text", value: node.value.slice(last, at) });
      out.push({ type: "link", url: workspacePath(m[2]) ?? m[2], children: [{ type: "text", value: m[2] }] });
      last = at + m[2].length;
    }
    if (!out.length) return node;
    if (last < node.value.length) out.push({ type: "text", value: node.value.slice(last) });
    return { type: "paragraph", children: out };
  }
  if (node.children && node.type !== "link")
    node.children = node.children.flatMap((c) => { const n = linkifyPaths(c); return n.type === "paragraph" && c.type === "text" ? n.children! : [n]; });
  return node;
}
const remarkPaths = () => (tree: Node) => { linkifyPaths(tree); };
const remarkPlugins = [[remarkGfm, { singleTilde: false }], remarkMath, remarkPaths] as const;

const MemoizedMarkdownBlock = memo(
  function MarkdownBlock({ content, onOpenFile, sources }: {
    content: string;
    onOpenFile?: (path: string) => void;
    sources?: Map<string, Source>;
  }) {
    const components = {
      ...markdownComponents,
      a({ href, children }: { href?: string; children?: React.ReactNode }) {
        const path = href && onOpenFile ? workspacePath(href) : null;
        if (path) {
          return (
            <a href={href} onClick={(e) => { e.preventDefault(); onOpenFile!(path); }} className="cursor-pointer">
              {children}
            </a>
          );
        }
        // A link the model wrote is promoted to a citation chip only when a
        // search actually returned that URL. One it invented stays an ordinary
        // link — the chip is a provenance claim, not a style.
        const hit = href && sources?.get(urlKey(href));
        if (hit) {
          return (
            <SourceChip
              source={hit}
              onOpen={() => track("source_opened", {
                url: hit.url, domain: domainOf(hit.url), placement: "inline" })}
            />
          );
        }
        return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
      },
    };
    return (
      <ReactMarkdown
        remarkPlugins={remarkPlugins as any}
        rehypePlugins={rehypePlugins as any}
        components={components as any}
      >
        {content}
      </ReactMarkdown>
    );
  },
  (prev, next) => prev.content === next.content && prev.onOpenFile === next.onOpenFile
    && prev.sources === next.sources,
);

export const TextPart = memo(function TextPart({ text, onOpenFile, sources }: {
  text: string;
  onOpenFile?: (path: string) => void;
  // Results the turn's searches returned, keyed by `urlKey`. Built once per
  // message so the identity stays stable across streamed tokens.
  sources?: Map<string, Source>;
}) {
  const escaped = escapeCurrencyDollars(text);
  const blocks = useMemo(() => parseMarkdownIntoBlocks(escaped), [escaped]);

  return (
    <div dir="auto" className="prose dark:prose-invert min-w-full">
      {blocks.map((block, index) => (
        <MemoizedMarkdownBlock key={index} content={block} onOpenFile={onOpenFile} sources={sources} />
      ))}
    </div>
  );
});
