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
      <img
        src={src}
        alt={alt || ""}
        className="rounded-xl max-w-full border border-border"
      />
      {caption && (
        <p className="text-sm text-muted-foreground mt-2 text-center">
          {caption}
        </p>
      )}
    </div>
  );
}
