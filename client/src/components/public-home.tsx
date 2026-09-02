import { useRef, useState } from "react";
import { InputBox } from "./input-box";
import { ExamplesGallery } from "./examples";
import { EmptyHero, Suggestions } from "./chat";
import { CyclsLogo } from "./cycls-logo";
import { IconButton } from "./icon";
import type { AppConfig } from "../hooks/use-chat";
import { useLang, setLang, t } from "../lib/i18n";
import { toggleDark } from "../lib/utils";
import { track } from "../lib/posthog";

// The signed-out face of the agent — the same empty screen a signed-in user
// gets (hero, composer, example gallery), fully explorable without an
// account. Sign-in happens at the first real action: sending stashes the
// draft in sessionStorage and hands over to CustomSignIn; the signed-in Chat
// restores the draft on mount (chat.tsx).
export function PublicHome({ config, onSignIn }: {
  config: AppConfig | null;
  onSignIn: () => void;
}) {
  const lang = useLang();
  const isAr = lang === "ar";
  const _active = config?.pass_metadata?.[isAr ? "ar" : "en"];
  const _en = config?.pass_metadata?.en;
  const meta = _active
    ? { ..._active, logo: _active.logo || _en?.logo || "", brand: _active.brand || _en?.brand || "" }
    : _en;
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const noop = () => {};

  const gate = (text?: string) => {
    const draft = (text ?? input).trim();
    if (draft) sessionStorage.setItem("cycls_draft", draft);
    track("sign_up_start", { has_draft: !!draft });
    onSignIn();
  };

  return (
    <div className="h-dvh flex flex-col bg-background">
      <header className="relative z-30 h-12 shrink-0" dir="ltr">
        <div className="mx-auto flex h-full max-w-full items-center justify-between px-4 sm:px-6">
          {meta?.brand ? (
            <span className="flex h-6 items-center">
              {meta.brand.startsWith("<") ? (
                <span className="flex h-6 items-center [&>svg]:h-6 [&>svg]:w-auto" dangerouslySetInnerHTML={{ __html: meta.brand }} />
              ) : (
                <img src={meta.brand} alt="" className="h-6 w-auto object-contain" />
              )}
            </span>
          ) : (
            <CyclsLogo className="h-5 fill-muted-foreground" />
          )}
          <div className="flex items-center gap-1">
            <button
              onClick={() => {
                const next = isAr ? "en" : "ar";
                setLang(next);
                track("language_changed", { to: next, source: "public_home" });
              }}
              className="text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer"
              aria-label="Toggle language"
            >
              <span className="text-xs font-medium w-4 h-4 flex items-center justify-center">{isAr ? "En" : "عربي"}</span>
            </button>
            <IconButton name="moon" onClick={() => toggleDark("public_home")} label="Toggle theme" />
            <button
              onClick={() => gate("")}
              className="ms-1 rounded-full bg-foreground px-3.5 py-1.5 text-sm font-medium text-background hover:opacity-90 transition-opacity cursor-pointer"
            >
              {t("signIn")}
            </button>
          </div>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-col items-center px-6 pb-16">
          <div className="flex min-h-[calc(50dvh-2rem)] w-full flex-col items-center justify-end">
          {meta && <EmptyHero meta={meta} />}
          <div className="w-full max-w-3xl">
            <InputBox
              textareaRef={textareaRef}
              input={input}
              setInput={setInput}
              handleKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); gate(); }
              }}
              handleSubmit={() => gate()}
              isStreaming={false}
              onStop={noop}
              listening={false}
              transcribing={false}
              startMic={noop}
              stopMic={noop}
              cancelMic={noop}
              voice={false}
              placeholder={meta ? (isAr ? `اسأل ${meta.name}` : `Ask ${meta.name}`) : undefined}
            />
            {!config?.examples_enabled && config?.suggestions && (
              <div className="relative">
                <div className="absolute inset-x-0 top-0">
                  <Suggestions onSelect={(text) => gate(text)} onPreview={setInput} input={input} />
                </div>
              </div>
            )}
          </div>
          </div>
          {config?.examples_enabled && (
            <ExamplesGallery
              className="mt-5"
              onUsePrompt={(text) => { setInput(text); textareaRef.current?.focus(); }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
