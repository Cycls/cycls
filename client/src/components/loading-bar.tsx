export function LoadingBar({ active = true }: { active?: boolean }) {
  return (
    <div className="h-0.5 overflow-hidden">
      {active && <div className="h-full w-1/3 bg-muted-foreground/30 rounded-full animate-[slide_1s_ease-in-out_infinite]" />}
    </div>
  );
}
