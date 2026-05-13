import { useState, useRef, useCallback, useEffect } from "react";
import { track } from "../lib/posthog";
import { useToast } from "../lib/toast";
import { reasonOf } from "./use-api";

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
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const startedAtRef = useRef<number>(0);
  const cancelledRef = useRef(false);
  const authHeadersRef = useRef(authHeaders);
  authHeadersRef.current = authHeaders;

  const stop = useCallback(() => {
    recorderRef.current?.stop();
  }, []);

  const cancel = useCallback(() => {
    cancelledRef.current = true;
    track("mic_cancelled");
    abortRef.current?.abort();
  }, []);

  const start = useCallback(async () => {
    if (recorderRef.current) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];
      startedAtRef.current = Date.now();
      cancelledRef.current = false;

      const recorder = new MediaRecorder(stream, { mimeType: "audio/mp4" });
      recorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        recorderRef.current = null;
        setListening(false);

        const blob = new Blob(chunksRef.current, { type: "audio/mp4" });
        chunksRef.current = [];
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
        form.append("file", blob, "voice.m4a");
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
    } catch {
      // Mic access denied or unavailable
      track("mic_permission_denied");
    }
  }, [onEnd]);

  useEffect(() => {
    return () => {
      recorderRef.current?.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      abortRef.current?.abort();
    };
  }, []);

  return { listening, transcribing, start, stop, cancel };
}
