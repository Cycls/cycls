import { useEffect, useState } from "react";

const VIDEO = /\.(mp4|webm|mov|m4v|ogv)(?:[?#]|$)/i;

// An image or video in markdown: `![demo](media/clip.mp4)` plays, anything else is a picture.
// A path without a scheme is a workspace file, fetched with the person's credentials by `resolve`.
export function Media({ src, alt, resolve }: { src: string; alt?: string; resolve?: (path: string) => Promise<string> }) {
  const local = !!resolve && !/^([a-z][a-z0-9+.-]*:|\/\/)/i.test(src);
  const [url, setUrl] = useState(local ? "" : src);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!local) { setUrl(src); return; }
    let blob = "", gone = false;
    setFailed(false);
    resolve!(src.replace(/^(\.\/|\/?workspace\/|\/)+/, ""))
      .then((u) => { blob = u; if (!gone) setUrl(u); })
      .catch(() => { if (!gone) setFailed(true); });
    return () => { gone = true; if (blob) URL.revokeObjectURL(blob); };
  }, [src, local, resolve]);
  const cls = "my-2 block max-h-[28rem] max-w-full rounded-lg";
  if (failed) return <span className="my-2 block text-xs text-muted-foreground" dir="auto">{alt || src}</span>;
  if (!url) return <span className="my-2 block h-40 w-full max-w-md animate-pulse rounded-lg bg-secondary" />;
  return VIDEO.test(src)
    ? <video src={url} controls preload="metadata" className={cls} />
    : <img src={url} alt={alt ?? ""} className={cls} />;
}
