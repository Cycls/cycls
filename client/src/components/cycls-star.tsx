import { useId } from "react";

// The Cycls stars, traced from the identity's نجوم.svg: the solid one, and the one with a diamond cut out.
const SOLID = "M85.7 16.1C90.8 33.4 94.4 41.1 101.5 49.8C112.1 62.5 123.9 69.4 147.1 75.8C154.6 77.9 160.8 79.9 160.8 80.2C160.8 80.5 155.3 82.4 148.6 84.1C126 90.2 115.3 95.8 104.7 106.9C94.9 117.2 91.3 124.8 83.3 151.6C81.9 156.5 80.5 160.2 80.3 160.1C80.2 160 78.4 154.1 76.4 147.2C74.4 140.3 71.8 132.2 70.6 129.2C64.4 113.2 49.5 97.9 33.2 90.9C30.9 89.9 22.4 87.1 14.2 84.8C6 82.4 0 80.2 0.8 79.9C1.6 79.5 8.6 77.5 16.3 75.4C32.8 70.5 42.3 66 50.7 58.9C63.4 48.1 69.3 37.9 75.9 14.9C78.2 6.8 80.4 0.5 80.8 0.9C81.1 1.3 83.3 8.2 85.7 16.1Z";
const HOLLOW = "M93.6 37.8C96.9 44.6 99.5 48 106.3 54.8C117.3 65.7 124.8 69.7 145.9 75.9C154.7 78.5 161.2 80.9 160.4 81.2C159.6 81.5 152.6 83.5 144.9 85.8C128.5 90.5 120.6 94.1 112.2 100.9C105.1 106.6 101 111.2 96.2 118.8C91.4 126.5 90.7 128.3 85.4 146.3C82.7 155.1 80.4 161.6 80.1 160.8C79.8 160 77.5 152.4 74.9 143.9C72.4 135.5 69.3 126.5 68 123.9C61.8 111.8 49.3 99.4 37 93.4C33.1 91.5 23.3 88 15.2 85.7C7 83.3 0.4 81.2 0.4 80.9C0.4 80.5 6.6 78.6 14.2 76.5C36.7 70.2 50.1 62.5 59.9 50C66.5 41.8 70.9 32.3 75.5 16.3C77.7 8.6 79.8 1.6 80.1 0.8C80.4 0 82.6 6 85 14.3C87.4 22.5 91.3 33.1 93.6 37.8ZM77.6 55.7C74.1 61 59.5 75.4 54.6 78.3C52.8 79.4 51.4 80.5 51.4 80.8C51.4 81.1 53.1 82.2 55.1 83.3C60.2 86 74.5 100.4 77.9 106.2L80.6 110.9L83.9 106.1C87.8 100.5 101.2 87.1 106.7 83.5L110.4 81L105.7 77.5C99.8 73.1 86.4 59.6 83.1 54.6L80.7 50.9L77.6 55.7Z";

export function Star({ size, className, hollow }: { size: number; className?: string; hollow?: boolean }) {
  return (
    <svg viewBox="0 0 161 161" width={size} height={size} className={className} fill="currentColor">
      <path fillRule="evenodd" d={hollow ? HOLLOW : SOLID} />
    </svg>
  );
}

// The glowing star: the brand's blue and orange, mixed into its ink, sweep through it over a faint glow of them
// (turning too, the loader's: `spin`).
export function GlowStar({ size = 16, spin }: { size?: number; spin?: boolean }) {
  const id = useId().replace(/\W/g, "");
  const mix = (c: string) => ({ stopColor: `color-mix(in oklab, ${c} 88%, currentColor)` });
  const sweep = <animateTransform attributeName="gradientTransform" type="translate" from="0" to="322" dur="3s" repeatCount="indefinite" />;
  return (
    <svg viewBox="0 0 161 161" width={size} height={size} className={spin ? "animate-[spin_1.8s_linear_infinite] overflow-visible" : "overflow-visible"}>
      <defs>
        <linearGradient id={`${id}i`} gradientUnits="userSpaceOnUse" x2="322" spreadMethod="repeat">
          <stop stopColor="currentColor" /><stop offset=".25" style={mix("#3171F6")} /><stop offset=".5" stopColor="currentColor" />
          <stop offset=".75" style={mix("#EF8733")} /><stop offset="1" stopColor="currentColor" />{sweep}
        </linearGradient>
        <linearGradient id={`${id}g`} gradientUnits="userSpaceOnUse" x2="322" spreadMethod="repeat">
          <stop stopColor="#3171F6" /><stop offset=".5" stopColor="#EF8733" /><stop offset="1" stopColor="#3171F6" />{sweep}
        </linearGradient>
        <filter id={`${id}b`} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="22" /></filter>
      </defs>
      <path fillRule="evenodd" d={HOLLOW} fill={`url(#${id}g)`} filter={`url(#${id}b)`} opacity={0.2} transform="translate(80.5 80.5) scale(1.15) translate(-80.5 -80.5)" />
      <path fillRule="evenodd" d={HOLLOW} fill={`url(#${id}i)`} />
    </svg>
  );
}
