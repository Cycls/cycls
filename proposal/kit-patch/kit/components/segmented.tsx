import type { ReactNode } from "react";
import { Tabs, TabsList, TabsTrigger } from "../ui/tabs";
import { cn } from "../lib/utils";

/** A view switcher on shadcn Tabs (no TabsContent: the app renders the view itself).
 *  Radix handles arrow keys, in reading order under <Direction.Provider> (AppShell).
 *  Each trigger is as wide as its label (flex-none: shadcn's flex-1 + a min-width gave
 *  every trigger an equal share, and long labels spilled out of their pill); when the row
 *  is wider than its box it scrolls sideways inside it (phones), never the page. */
export function Segmented<V extends string>({ value, onChange, options, label, className }: {
  value: V; onChange: (v: V) => void; label: string; className?: string;
  options: { value: V; label: ReactNode; icon?: ReactNode; ariaLabel?: string }[];
}) {
  return (
    <Tabs value={value} onValueChange={(v) => onChange(v as V)} className={cn("min-w-0 max-w-full", className)}>
      <TabsList aria-label={label} data-kit-segmented=""
        className="relative h-10 max-w-full justify-start overflow-x-auto overflow-y-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {options.map((o) => (
          <TabsTrigger key={o.value} value={o.value} aria-label={o.ariaLabel} className={cn("min-w-10 flex-none px-3")}>{o.icon}{o.label}</TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
