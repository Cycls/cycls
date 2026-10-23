import { createContext } from "react";

// Places in the canvas's file header a document view may fill (an editor's "Last modified", its Open ⌄),
// so a file has one header row rather than the canvas's and its own. Null outside the canvas (a share).
export type CanvasHeaderSlots = { start: HTMLElement | null; end: HTMLElement | null };
export const CanvasHeaderSlot = createContext<CanvasHeaderSlots>({ start: null, end: null });
