import { cn } from "../../lib/utils";
import { useDarkMode } from "../../hooks/use-dark-mode";
import { useEffect, useState } from "react";
import { codeToHtml } from "shiki";

export function CodeBlock({
  children,
  className,
  ...props
}: {
  children?: React.ReactNode;
  className?: string;
} & React.HTMLProps<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "not-prose flex w-full flex-col overflow-clip border",
        "border-border bg-card text-card-foreground rounded-xl",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function CodeBlockGroup({
  children,
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("flex items-center justify-between", className)}
      {...props}
    >
      {children}
    </div>
  );
}

export function CodeBlockCode({
  code,
  language = "text",
  className,
  ...props
}: {
  code: string;
  language?: string;
  className?: string;
} & React.HTMLProps<HTMLDivElement>) {
  const isDark = useDarkMode();
  const [highlightedHtml, setHighlightedHtml] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function highlight() {
      try {
        const html = await codeToHtml(code, {
          lang: language,
          theme: isDark ? "github-dark" : "github-light",
        });
        if (!cancelled) setHighlightedHtml(html);
      } catch {
        // fallback to plain text on unknown language
        if (!cancelled) setHighlightedHtml(null);
      }
    }
    highlight();
    return () => {
      cancelled = true;
    };
  }, [code, language, isDark]);

  const classNames = cn(
    "w-full overflow-x-auto text-[14px] [&>pre]:px-4 [&>pre]:py-4 [&>pre]:!bg-background",
    className,
  );

  return highlightedHtml ? (
    <div
      className={classNames}
      dangerouslySetInnerHTML={{ __html: highlightedHtml }}
      {...props}
    />
  ) : (
    <div className={classNames} {...props}>
      <pre className="px-4 py-4">
        <code>{code}</code>
      </pre>
    </div>
  );
}
