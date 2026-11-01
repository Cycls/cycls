import { useCallback, useEffect, useRef, useState } from "react";
import { track } from "../lib/analytics";
import type { Message } from "./use-chat";

// A voice conversation (Web.speech): the mic listens and stops itself once the person falls quiet, what they
// said is sent, the reply is read aloud a sentence at a time while it streams, and the mic listens again.
// The mic is off while a reply is read, so the speakers never answer themselves.

const QUIET_MS = 1300;      // this long quiet after speech ends the recording
const GIVE_UP_MS = 30_000;  // nothing said for this long ends the conversation
const AHEAD = 3;            // sentences fetched ahead of the one playing
// A WAV with no samples: played inside the tap that starts a conversation, it lets the page play sound later (iOS).
const SILENCE = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=";

export type TalkPhase = "off" | "listening" | "thinking" | "speaking";
type Mic = {
  listening: boolean; transcribing: boolean; analyser: AnalyserNode | null;
  start: () => Promise<boolean>; stop: () => void; cancel: () => void;
};

// What a reply says out loud: no code, table rows, addresses or markdown marks. It stays a prefix of itself as
// the reply grows, so what was read stays read: an unclosed code fence hides the rest until it closes.
export function speakable(text: string): string {
  const open = (text.match(/```/g) || []).length % 2 ? text.lastIndexOf("```") : -1;
  return (open >= 0 ? text.slice(0, open) : text)
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/^\s*\|.*$/gm, "")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/<\/?｜[^>]*>?/g, "")   // a model's own markup that reached the text (DeepSeek's ｜DSML｜)
    .replace(/[*_#>`~|]/g, "");
}

// Intl.Segmenter knows ؟ and ۔ and that ، ends no sentence; without it, a line or a stop ends one.
type Segmenter = { segment: (text: string) => Iterable<{ segment: string }> };
const Segmenter = (Intl as unknown as { Segmenter?: new (locale?: string, o?: { granularity: "sentence" }) => Segmenter }).Segmenter;
const segmenter = Segmenter ? new Segmenter(undefined, { granularity: "sentence" }) : null;
export const sentences = (text: string): string[] =>
  segmenter ? [...segmenter.segment(text)].map((s) => s.segment) : text.match(/[^.!?؟۔\n]*[.!?؟۔\n]+\s*|[^.!?؟۔\n]+$/g) || [];

export const replyText = (m: Message) =>
  (m.parts || []).filter((p) => p.type === "text").map((p) => p.text || "").join("\n\n") || m.content;

export function useTalk({ messages, isStreaming, mic, authHeaders }: {
  messages: Message[]; isStreaming: boolean; mic: Mic;
  authHeaders?: () => Promise<Record<string, string>>;
}) {
  const [on, setOn] = useState(false);
  const [waiting, setWaiting] = useState(false);     // what was said is on its way, the reply not begun
  const [speaking, setSpeaking] = useState(false);
  const replyRef = useRef(-1);                         // the reply being read, by index; -1 none
  const readRef = useRef(0);                           // how much of its speakable text is queued
  const queueRef = useRef<{ text: string; audio?: Promise<Blob | null> }[]>([]);
  const playingRef = useRef(false);
  const startingRef = useRef(false);                   // the mic asked for and not yet on
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const authRef = useRef(authHeaders);
  authRef.current = authHeaders;

  const fetchSpeech = (text: string) =>
    (authRef.current ? authRef.current() : Promise.resolve({} as Record<string, string>))
      .then((h) => fetch("/speak", { method: "POST", headers: { ...h, "Content-Type": "application/json" }, body: JSON.stringify({ text }) }))
      .then((r) => (r.ok ? r.blob() : null))
      .catch(() => null);

  // Plays the queue in order, fetching a few sentences ahead; a sentence that couldn't be read is skipped.
  const pump = useCallback(() => {
    const q = queueRef.current;
    q.slice(0, AHEAD).forEach((item) => { item.audio ??= fetchSpeech(item.text); });
    if (playingRef.current) return;
    if (!q.length) { setSpeaking(false); return; }
    const item = q[0];
    playingRef.current = true;
    setSpeaking(true);
    void item.audio!.then((blob) => {
      if (queueRef.current[0] !== item) return;   // hushed meanwhile
      const next = () => { queueRef.current.shift(); playingRef.current = false; pump(); };
      const el = audioRef.current;
      if (!blob || !el) return next();
      const url = URL.createObjectURL(blob);
      el.onended = el.onerror = () => { URL.revokeObjectURL(url); next(); };
      el.src = url;
      el.play().catch(() => next());
    });
  }, []);

  const hush = useCallback(() => {
    queueRef.current = [];
    playingRef.current = false;
    replyRef.current = -1;
    audioRef.current?.pause();
    setSpeaking(false);
  }, []);

  const start = useCallback(() => {
    audioRef.current ??= new Audio();
    audioRef.current.src = SILENCE;
    audioRef.current.play().catch(() => {});
    setOn(true);
    track("talk_started");
  }, []);

  const end = useCallback(() => {
    setOn(false);
    setWaiting(false);
    hush();
    mic.cancel();
    track("talk_ended");
  }, [hush, mic.cancel]);   // eslint-disable-line react-hooks/exhaustive-deps

  // The words the mic heard: something said is sent by the chat, and its reply is the one read. True in a
  // conversation, so the chat marks the turn spoken.
  const heard = useCallback((text: string) => { if (on && text.trim()) setWaiting(true); return on; }, [on]);

  useEffect(() => {
    if (!waiting) return;
    if (isStreaming) { replyRef.current = messages.length - 1; readRef.current = 0; setWaiting(false); return; }
    const id = setTimeout(() => setWaiting(false), 8000);   // the send never began a reply: listen again
    return () => clearTimeout(id);
  }, [waiting, isStreaming, messages.length]);

  // The reply, read as it streams: every finished sentence is queued, and the last one when the reply ends.
  useEffect(() => {
    const m = messages[replyRef.current];
    if (!on || !m || m.role !== "assistant") return;
    const said = speakable(replyText(m));
    const parts = sentences(said.slice(readRef.current));
    for (const s of isStreaming ? parts.slice(0, -1) : parts) {
      readRef.current += s.length;
      if (s.trim()) queueRef.current.push({ text: s.trim() });
    }
    if (!isStreaming) replyRef.current = -1;
    pump();
  }, [messages, isStreaming, on, pump]);

  // Listen again once all is said: the reply being read has ended (or was hushed), nothing is left to read, the
  // mic is idle. Said while another reply runs, the words wait in the chat's queue.
  useEffect(() => {
    if (!on || waiting || (isStreaming && replyRef.current >= 0) || speaking || mic.listening || mic.transcribing
        || queueRef.current.length || playingRef.current || startingRef.current) return;
    startingRef.current = true;
    void mic.start().then((ok) => { startingRef.current = false; if (!ok) end(); });
  }, [on, waiting, isStreaming, speaking, mic.listening, mic.transcribing]);   // eslint-disable-line react-hooks/exhaustive-deps

  // The recording ends itself once the person has spoken and gone quiet; the bar for "spoken" sits above the
  // room's own noise, the quietest the mic has heard.
  useEffect(() => {
    const a = mic.analyser;
    if (!on || !a || !mic.listening) return;
    const buf = new Float32Array(a.fftSize);
    const began = Date.now();
    let floor = 1, heardAny = false, quietSince = began;
    const id = setInterval(() => {
      a.getFloatTimeDomainData(buf);
      const level = Math.sqrt(buf.reduce((s, v) => s + v * v, 0) / buf.length);
      floor = Math.min(floor, Math.max(level, 0.002));
      const now = Date.now();
      if (level > Math.max(0.02, floor * 4)) { heardAny = true; quietSince = now; }
      else if (heardAny && now - quietSince > QUIET_MS) { clearInterval(id); mic.stop(); }
      else if (!heardAny && now - began > GIVE_UP_MS) { clearInterval(id); end(); }
    }, 100);
    return () => clearInterval(id);
  }, [on, mic.analyser, mic.listening]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => { audioRef.current?.pause(); }, []);

  const phase: TalkPhase = !on ? "off" : mic.listening ? "listening" : speaking ? "speaking" : "thinking";
  return { phase, start, end, hush, heard };
}
