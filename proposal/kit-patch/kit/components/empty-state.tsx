import type { ReactNode } from "react";
import { DatabaseZap } from "lucide-react";
import { cn } from "../lib/utils";
import { Button } from "../ui/button";
import { useKitT } from "../strings";

export function EmptyState({ icon, title, body, actions, className }: {
  icon?: ReactNode; title: ReactNode; body?: ReactNode; actions?: ReactNode; className?: string;
}) {
  return (
    <div className={cn("mx-auto flex max-w-md flex-col items-center gap-3 px-4 py-12 text-center", className)}>
      {icon && <div className="grid size-14 place-items-center rounded-2xl bg-primary-soft text-primary [&_svg]:size-7">{icon}</div>}
      <h2 className="text-lg font-semibold">{title}</h2>
      {body && <p className="text-sm text-muted-foreground">{body}</p>}
      {actions && <div className="mt-2 flex flex-wrap justify-center gap-2">{actions}</div>}
    </div>
  );
}

/** A loading state. aria-busy is what scripts/check.mjs waits on before it measures. */
export function Spinner({ label, className }: { label: string; className?: string }) {
  return (
    <div role="status" aria-busy="true" className={cn("flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground", className)}>
      <span className="size-4 animate-spin rounded-full border-2 border-border border-t-primary" aria-hidden />
      {label}
    </div>
  );
}

/** The one "load example" action, worded the same in every app («إضافة بيانات تجريبية» —
 *  never «تحميل», which reads "download"). Pass `rows.loadDemo`. */
export function LoadExampleButton({ onClick, variant = "outline", className }: {
  onClick: () => void | Promise<unknown>; variant?: "default" | "outline" | "secondary" | "ghost"; className?: string;
}) {
  const t = useKitT();
  return <Button variant={variant} className={className} onClick={() => { void onClick(); }}><DatabaseZap />{t("loadExample")}</Button>;
}
