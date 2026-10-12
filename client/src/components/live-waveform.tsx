import { useEffect, useRef } from "react";
import { cn } from "../lib/utils";

// The mic's level as bars scrolling in from the right; silence draws as dots.
// Adapted from ElevenLabs UI's LiveWaveform, scrolling mode (MIT, © 2025 Eleven Labs Inc.).
const BAR = 3, GAP = 3, EVERY_MS = 50, SENSITIVITY = 1.6, FADE = 24;

export function LiveWaveform({ analyser, className }: { analyser: AnalyserNode; className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const bins = new Uint8Array(analyser.frequencyBinCount);
    const from = Math.floor(bins.length * 0.05), to = Math.floor(bins.length * 0.4);   // where speech is
    let history: number[] = [], last = -Infinity, frame = 0;
    const draw = (now: number) => {
      const { width, height } = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      if (canvas.width !== Math.round(width * dpr)) { canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr); }
      const count = Math.floor(width / (BAR + GAP));
      if (now - last >= EVERY_MS) {
        last = now;
        analyser.getByteFrequencyData(bins);
        let sum = 0;
        for (let i = from; i < to; i++) sum += bins[i];
        history = [...history, Math.min(1, (sum / (to - from) / 255) * SENSITIVITY)].slice(-count);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = getComputedStyle(canvas).color;
      for (let i = 0; i < count; i++) {
        const v = history[history.length - 1 - i] ?? 0;   // newest on the right; before the first, silence
        const h = Math.max(BAR, v * height * 0.8);
        ctx.globalAlpha = 0.4 + 0.6 * v;
        ctx.beginPath();
        ctx.roundRect(width - (i + 1) * (BAR + GAP), (height - h) / 2, BAR, h, BAR / 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "destination-out";   // the oldest bars fade out at the left
      const fade = ctx.createLinearGradient(0, 0, FADE, 0);
      fade.addColorStop(0, "rgba(0,0,0,1)");
      fade.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = fade;
      ctx.fillRect(0, 0, FADE, height);
      ctx.globalCompositeOperation = "source-over";
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [analyser]);
  return <canvas ref={canvasRef} className={cn("block", className)} data-testid="live-waveform" aria-hidden />;
}
