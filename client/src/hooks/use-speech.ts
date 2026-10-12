import { useState, useRef, useCallback, useEffect } from "react";
import { track } from "../lib/analytics";
import { useToast } from "../lib/toast";
import { t } from "../lib/i18n";
import { reasonOf } from "./use-api";

// Safari and Chrome record mp4; Firefox can't, and records webm (or ogg).
const TYPES = ["audio/mp4", "audio/webm;codecs=opus", "audio/ogg;codecs=opus"];
const extension = (type: string) => (type.includes("webm") ? "webm" : type.includes("ogg") ? "ogg" : "m4a");

export function useSpeechRecognition({
  onEnd,
  authHeaders,
}: {
  onEnd: (text: string) => void;
  authHeaders?: () => Promise<Record<string, string>>;
}) {
  const { error: toastError } = useToast();
  const [listening, setListening] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);   // the live level, for the wave
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<AudioContext | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const startedAtRef = useRef<number>(0);
  const cancelledRef = useRef(false);
  const authHeadersRef = useRef(authHeaders);
  authHeadersRef.current = authHeaders;

  const release = useCallback(() => {   // the mic off, and the wave with it
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    audioRef.current?.close().catch(() => {});
    audioRef.current = null;
    setAnalyser(null);
  }, []);

  const stop = useCallback(() => {
    recorderRef.current?.stop();
  }, []);

  // While recording it discards the audio; while transcribing it drops the answer.
  const cancel = useCallback(() => {
    cancelledRef.current = true;
    track("mic_cancelled");
    abortRef.current?.abort();
    recorderRef.current?.stop();
  }, []);

  const start = useCallback(async () => {
    if (recorderRef.current) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];
      startedAtRef.current = Date.now();
      cancelledRef.current = false;

      const mimeType = TYPES.find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;

      try {   // the wave is extra: recording goes on without it
        const ctx = new AudioContext();
        const node = ctx.createAnalyser();
        node.fftSize = 256;
        ctx.createMediaStreamSource(stream).connect(node);
        audioRef.current = ctx;
        setAnalyser(node);
      } catch { /* no wave */ }

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        release();
        recorderRef.current = null;
        setListening(false);

        const type = recorder.mimeType || mimeType || "audio/mp4";
        const blob = new Blob(chunksRef.current, { type });
        chunksRef.current = [];
        if (cancelledRef.current) {
          onEnd("");
          return;
        }
        const duration_ms = Date.now() - startedAtRef.current;

        if (blob.size < 1000) {
          track("mic_stopped", { duration_ms, audio_bytes: blob.size, reason: "too_short" });
          onEnd("");
          return;
        }

        track("mic_stopped", { duration_ms, audio_bytes: blob.size });
        setTranscribing(true);

        const controller = new AbortController();
        abortRef.current = controller;
        const form = new FormData();
        form.append("file", blob, `voice.${extension(type)}`);
        const t0 = Date.now();
        try {
          const headers = authHeadersRef.current ? await authHeadersRef.current() : {};
          const res = await fetch("/transcribe", { method: "POST", body: form, headers, signal: controller.signal });
          if (res.ok) {
            const data = await res.json();
            const text = data.text || "";
            track("mic_transcribed", {
              audio_ms: duration_ms,
              transcribe_ms: Date.now() - t0,
              text_length: text.length,
              empty: !text,
            });
            onEnd(text);
          } else {
            track("mic_transcription_failed", { status: res.status });
            toastError(await reasonOf(res));
            onEnd("");
          }
        } catch {
          if (!cancelledRef.current) {
            track("mic_transcription_failed", { status: 0 });
          }
          onEnd("");
        } finally {
          abortRef.current = null;
          setTranscribing(false);
        }
      };

      recorder.start();
      setListening(true);
      track("mic_started");
    } catch (e) {
      release();
      recorderRef.current = null;
      track("mic_permission_denied", { reason: (e as Error)?.name });   // NotAllowedError, NotFoundError, NotSupportedError…
      toastError(t("micUnavailable"));
    }
  }, [onEnd, release, toastError]);

  useEffect(() => {
    return () => {
      recorderRef.current?.stop();
      release();
      abortRef.current?.abort();
    };
  }, [release]);

  return { listening, transcribing, analyser, start, stop, cancel };
}
