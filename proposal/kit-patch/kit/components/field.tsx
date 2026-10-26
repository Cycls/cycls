import { useId, type ComponentProps, type ReactNode } from "react";
import { Label } from "../ui/label";
import { NativeSelect, NativeSelectOption } from "../ui/native-select";
import { cn } from "../lib/utils";

/** Label + control + hint/error, wired with ids. `children(id, describedBy)` renders the
 *  shadcn control (Input, Textarea, NativeSelect…). NativeSelect's wrapper is w-fit in
 *  shadcn; inside a Field it is stretched to the column. */
export function Field({ label, hint, error, children, className }: {
  label: ReactNode; hint?: ReactNode; error?: ReactNode; className?: string;
  children: (id: string, describedBy?: string) => ReactNode;
}) {
  const id = useId();
  const desc = hint || error ? `${id}-d` : undefined;
  return (
    <div className={cn("flex min-w-0 flex-col gap-2 *:data-[slot=native-select-wrapper]:w-full", className)}>
      <Label htmlFor={id}>{label}</Label>
      {children(id, desc)}
      {(hint || error) && <p id={desc} className={cn("text-xs", error ? "text-destructive" : "text-muted-foreground")}>{error || hint}</p>}
    </div>
  );
}

/** shadcn NativeSelect from an options list, stretched to its container (shadcn's wrapper
 *  is w-fit). Native: the platform picker on phones, RTL for free, no portal. */
export function SimpleSelect({ options, className, ...p }: Omit<ComponentProps<typeof NativeSelect>, "children"> & { options: { value: string; label: string }[] }) {
  return (
    <div className={cn("min-w-0 *:data-[slot=native-select-wrapper]:w-full", className)}>
      <NativeSelect {...p}>
        {options.map((o) => <NativeSelectOption key={o.value} value={o.value}>{o.label}</NativeSelectOption>)}
      </NativeSelect>
    </div>
  );
}
