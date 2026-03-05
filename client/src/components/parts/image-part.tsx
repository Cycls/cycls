export function ImagePart({
  src,
  alt,
  caption,
}: {
  src: string;
  alt?: string;
  caption?: string;
}) {
  return (
    <div className="my-3">
      <img src={src} alt={alt || ""} className="rounded-lg max-w-full" />
      {caption && (
        <p className="text-sm text-[var(--text-secondary)] mt-2 text-center">
          {caption}
        </p>
      )}
    </div>
  );
}
