import { useState, useRef, useCallback, useEffect } from "react";

export function useSpeechRecognition({
  onEnd,
  authHeaders,
}: {
  onEnd: (text: string) => void;
  authHeaders?: () => Promise<Record<string, string>>;
}) {
  const [listening, setListening] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const authHeadersRef = useRef(authHeaders);
  authHeadersRef.current = authHeaders;

  const stop = useCallback(() => {
    recorderRef.current?.stop();
  }, []);

  const start = useCallback(async () => {
    if (recorderRef.current) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];

      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        recorderRef.current = null;
        setListening(false);

        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        chunksRef.current = [];

        if (blob.size < 1000) {
          onEnd("");
          return;
        }

        setTranscribing(true);

        const form = new FormData();
        form.append("file", blob, "voice.webm");
        try {
          const headers = authHeadersRef.current ? await authHeadersRef.current() : {};
          const token = headers["Authorization"]?.replace("Bearer ", "");
          const url = token ? `/transcribe?token=${encodeURIComponent(token)}` : "/transcribe";
          const res = await fetch(url, { method: "POST", body: form });
          if (res.ok) {
            const data = await res.json();
            onEnd(data.text || "");
          } else {
            onEnd("");
          }
        } catch {
          onEnd("");
        } finally {
          setTranscribing(false);
        }
      };

      recorder.start();
      setListening(true);
    } catch {
      // Mic access denied or unavailable
    }
  }, [onEnd]);

  useEffect(() => {
    return () => {
      recorderRef.current?.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  return { listening, transcribing, start, stop };
}
