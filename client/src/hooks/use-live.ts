import { useCallback, useEffect, useRef, useState } from "react";
import { track } from "../lib/analytics";
import { useToast } from "../lib/toast";
import { t } from "../lib/i18n";
import type { Message } from "./use-chat";
import { replyText, speakable, type TalkPhase } from "./use-talk";

// A live conversation (Web.realtime): the page and a speech-to-speech model talk over WebRTC, the call opened by
// the server (/realtime) so the page holds no key. The person can cut in; the model's own turn-taking decides.
// Anything past small talk comes back as an `ask_agent` call: it goes to the chat as a spoken turn, and the
// reply, once it ends, goes back to the voice to say.

const WAIT_MS = 60_000;   // a request the chat never began a reply to is answered as not taken
const OPEN_MS = 15_000;   // a call whose channel hasn't opened by then never will: say so, not silence

type Call = { type?: string; name?: string; call_id?: string; arguments?: string };

export function useLive({ messages, isStreaming, send, authHeaders }: {
  messages: Message[]; isStreaming: boolean; send: (text: string, language?: string) => void;
  authHeaders?: () => Promise<Record<string, string>>;
}) {
  const { error: toastError } = useToast();
  const [phase, setPhase] = useState<TalkPhase>("off");
  const [waiting, setWaiting] = useState(false);   // a request is with the chat, its reply not begun
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const callRef = useRef<string | null>(null);     // the ask_agent call waiting on the chat
  const replyRef = useRef(-1);                     // that reply, by index, once it has begun
  const authRef = useRef(authHeaders);
  authRef.current = authHeaders;
  const sendRef = useRef(send);
  sendRef.current = send;

  const emit = (ev: object) => { if (dcRef.current?.readyState === "open") dcRef.current.send(JSON.stringify(ev)); };
  const answer = (text: string) => {
    const id = callRef.current;
    if (!id) return;
    callRef.current = null;
    emit({ type: "conversation.item.create", item: { type: "function_call_output", call_id: id, output: text } });
    emit({ type: "response.create" });
  };

  const end = useCallback(() => {
    if (!pcRef.current) return;
    pcRef.current.getSenders().forEach((s) => s.track?.stop());
    pcRef.current.close();
    dcRef.current?.close();
    pcRef.current = dcRef.current = null;
    callRef.current = null;
    replyRef.current = -1;
    setWaiting(false);
    setPhase("off");
    track("live_ended");
  }, []);

  // Whatever stops the voice is said, and tracked with its reason: a silent voice reads as a broken one.
  const fail = (reason: string) => {
    track("live_failed", { reason: reason.slice(0, 60) });
    toastError(t("liveFailed"));
    end();
  };
  const failRef = useRef(fail);
  failRef.current = fail;

  const onEvent = (ev: { type?: string; error?: { code?: string; message?: string };
                         response?: { output?: Call[]; status?: string; status_details?: { error?: { code?: string; type?: string } } } }) => {
    if (ev.type === "error") return fail(ev.error?.code || ev.error?.message || "error");
    if (ev.type === "response.done" && ev.response?.status === "failed")
      return fail(ev.response.status_details?.error?.code || ev.response.status_details?.error?.type || "response_failed");
    if (ev.type === "output_audio_buffer.started") setPhase("speaking");
    else if (ev.type === "output_audio_buffer.stopped" || ev.type === "output_audio_buffer.cleared")
      setPhase(callRef.current ? "thinking" : "listening");
    else if (ev.type === "response.done") {
      for (const out of ev.response?.output || []) {
        if (out.type !== "function_call" || out.name !== "ask_agent" || !out.call_id) continue;
        let request = "", language = "";
        try { ({ request = "", language = "" } = JSON.parse(out.arguments || "{}")); } catch { /* no request */ }
        callRef.current = out.call_id;
        if (!String(request).trim()) { answer("No request was given."); continue; }
        setWaiting(true);
        setPhase("thinking");
        sendRef.current(String(request), String(language || "") || undefined);   // the language the voice heard
      }
    }
  };
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const start = useCallback(async () => {
    if (pcRef.current) return;
    setPhase("thinking");
    track("live_started");
    try {
      const pc = new RTCPeerConnection();
      pcRef.current = pc;
      const audio = new Audio();   // made in the tap, so it may play
      audio.autoplay = true;
      pc.ontrack = (e) => { audio.srcObject = e.streams[0]; };
      const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
      pc.addTrack(mic.getTracks()[0], mic);
      const dc = pc.createDataChannel("oai-events");
      dcRef.current = dc;
      dc.onopen = () => setPhase("listening");
      pc.onconnectionstatechange = () => { if (pc.connectionState === "failed") failRef.current("connection_failed"); };
      setTimeout(() => { if (pcRef.current === pc && dc.readyState !== "open") failRef.current("no_connection"); }, OPEN_MS);
      dc.onmessage = (e) => { try { onEventRef.current(JSON.parse(e.data)); } catch { /* not an event */ } };
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      const headers = authRef.current ? await authRef.current() : {};
      const r = await fetch("/realtime", { method: "POST", body: offer.sdp, headers: { ...headers, "Content-Type": "application/sdp" } });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      if (pcRef.current !== pc) return;   // ended meanwhile
      await pc.setRemoteDescription({ type: "answer", sdp: await r.text() });
    } catch (e) {
      if ((e as Error)?.name === "NotAllowedError") { track("live_failed", { reason: "mic" }); toastError(t("micUnavailable")); end(); }
      else fail((e as Error)?.message || "start");
    }
  }, [end, toastError]);

  // The voice stops talking; what the person says next is heard.
  const hush = useCallback(() => {
    emit({ type: "response.cancel" });
    emit({ type: "output_audio_buffer.clear" });
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!waiting) return;
    if (isStreaming) { replyRef.current = messages.length - 1; setWaiting(false); return; }
    const id = setTimeout(() => { setWaiting(false); answer("The agent couldn't take the request just now."); }, WAIT_MS);
    return () => clearTimeout(id);
  }, [waiting, isStreaming, messages.length]);   // eslint-disable-line react-hooks/exhaustive-deps

  // The reply has ended: its speakable words go back to the voice.
  useEffect(() => {
    const m = messages[replyRef.current];
    if (isStreaming || !m || m.role !== "assistant") return;
    replyRef.current = -1;
    answer(speakable(replyText(m)).trim().slice(0, 6000) || "The agent finished, with nothing to say aloud.");
    setPhase("listening");
  }, [isStreaming, messages]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => { pcRef.current?.close(); }, []);

  return { phase, start, end, hush };
}
