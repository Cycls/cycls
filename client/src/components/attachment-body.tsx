import type { Attachment } from "../hooks/use-chat";
import { tintTile, tintLabel } from "./canvas-utils";

export function AttachmentBody({ attachment }: { attachment: Attachment }) {
  const { name, type, url, size, status } = attachment;
  const isImg = type.startsWith("image/");
  return (
    <>
      <div className="bg-secondary flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-lg relative" style={isImg ? undefined : tintTile(name)}>
        {isImg ? (
          <img src={url} alt={name} className={`size-full object-cover ${status === "uploading" ? "opacity-40" : ""}`} />
        ) : (
          <span className={`text-[10px] font-medium uppercase ${status === "error" ? "text-red-500" : "text-muted-foreground"}`} style={status === "error" ? undefined : tintLabel(name)}>
            {name.split(".").pop()}
          </span>
        )}
        {status === "uploading" && (
          <div className="absolute inset-0 flex items-center justify-center">
            <svg className="size-5 animate-spin text-muted-foreground" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
        )}
      </div>
      <div className="flex flex-col overflow-hidden min-w-0">
        <span className={`truncate text-xs font-medium max-w-[120px] ${status === "error" ? "text-red-600 dark:text-red-400" : "text-foreground"}`}>{name}</span>
        <span className={`text-xs ${status === "error" ? "text-red-500 dark:text-red-400" : "text-muted-foreground"}`}>
          {status === "error" ? "Upload failed" : (size / 1024).toFixed(1) + " kB"}
        </span>
      </div>
    </>
  );
}
