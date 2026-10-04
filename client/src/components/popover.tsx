import { createPortal } from "react-dom";
import { useEscape } from "../hooks/use-escape";

export function Popover({ open, onClose, className, dim, children }: {
  open: boolean;
  onClose: () => void;
  className: string;
  dim?: boolean;
  children: React.ReactNode;
}) {
  useEscape(onClose, open);
  if (!open) return null;
  return createPortal(
    <>
      <div
        className={`fixed inset-0 z-[70] ${dim ? "bg-black/50 backdrop-blur-sm" : ""}`}
        onClick={onClose}
      />
      <div className={`fixed z-[80] ${className}`}>{children}</div>
    </>,
    document.body,
  );
}
