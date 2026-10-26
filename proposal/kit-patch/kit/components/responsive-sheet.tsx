import { useEffect, type ReactNode } from "react";
import { XIcon } from "lucide-react";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "../ui/dialog";
import { Drawer, DrawerContent, DrawerDescription, DrawerTitle } from "../ui/drawer";
import { Button } from "../ui/button";
import { holdRefresh } from "../cycls";
import { useKitT } from "../strings";
import { useMediaQuery } from "../hooks/use-media-query";
import { cn } from "../lib/utils";

/** shadcn Drawer (vaul, bottom) under 640 px, shadcn Dialog above — the shadcn
 *  "responsive dialog" pattern. Header, scrolling body, sticky footer. The turn_end reload
 *  waits while it is open. */
export function ResponsiveSheet({ open, onOpenChange, title, description, children, footer, className }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: ReactNode; description?: ReactNode;
  children: ReactNode; footer?: ReactNode; className?: string;
}) {
  const t = useKitT();
  const desktop = useMediaQuery("(min-width: 640px)");
  useEffect(() => (open ? holdRefresh() : undefined), [open]);
  const desc = description ?? (typeof title === "string" ? title : "");

  if (desktop) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent showCloseButton={false} className={cn("flex max-h-[90dvh] flex-col gap-0 p-0 sm:max-w-xl", className)}>
          <div className="flex items-start gap-3 border-b px-5 py-4">
            <div className="min-w-0 flex-1 space-y-1">
              <DialogTitle className="break-words leading-snug">{title}</DialogTitle>
              <DialogDescription className={description ? undefined : "sr-only"}>{desc}</DialogDescription>
            </div>
            <DialogClose asChild>
              <Button variant="ghost" size="icon" className="-me-2 shrink-0" aria-label={t("close")}><XIcon /></Button>
            </DialogClose>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && <div className="flex flex-wrap items-center justify-end gap-2 border-t px-5 py-3">{footer}</div>}
        </DialogContent>
      </Dialog>
    );
  }
  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent className={cn("max-h-[92dvh]", className)}>
        <div className="flex items-start gap-3 border-b px-4 pb-3 pt-2">
          <div className="min-w-0 flex-1 space-y-1 text-start">
            <DrawerTitle className="break-words leading-snug">{title}</DrawerTitle>
            <DrawerDescription className={description ? undefined : "sr-only"}>{desc}</DrawerDescription>
          </div>
          <Button variant="ghost" size="icon" className="-me-2 shrink-0" aria-label={t("close")} onClick={() => onOpenChange(false)}><XIcon /></Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4" data-vaul-no-drag>{children}</div>
        {footer && <div className="flex flex-wrap items-center justify-end gap-2 border-t px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">{footer}</div>}
      </DrawerContent>
    </Drawer>
  );
}

/** Yes/no for a destructive action. */
export function Confirm({ open, onOpenChange, title, body, confirmLabel, onConfirm, danger = true }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: ReactNode; body?: ReactNode;
  confirmLabel: string; onConfirm: () => void; danger?: boolean;
}) {
  const t = useKitT();
  return (
    <ResponsiveSheet open={open} onOpenChange={onOpenChange} title={title}
      footer={<>
        <Button variant="outline" onClick={() => onOpenChange(false)}>{t("cancel")}</Button>
        <Button variant={danger ? "destructive" : "default"} onClick={() => { onConfirm(); onOpenChange(false); }}>{confirmLabel}</Button>
      </>}>
      {body && <p className="text-sm text-muted-foreground">{body}</p>}
    </ResponsiveSheet>
  );
}
