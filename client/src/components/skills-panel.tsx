// The Skills tab (docs/notes/skills.md): every skill this person's chats may load with their own switch,
// the org's switch for an org admin, and adding, downloading and removing where they may publish.
import { useEffect, useRef, useState } from "react";
import { Switch } from "./connectors-dialog";
import type { ChatApi } from "../hooks/use-chat";
import { t } from "../lib/i18n";
import { cn } from "../lib/utils";
import { track } from "../lib/analytics";

type Scope = "org" | "workspace" | "me";
type Skill = { name: string; description: string; source: Scope | "dev"; version: number | null; on: boolean; allowed: boolean; manage: boolean };
type Skills = { skills: Skill[]; scopes: Scope[]; org_admin: boolean };
const SOURCE = { dev: "skillBuiltIn", org: "skillOrg", workspace: "skillWorkspace", me: "skillMine" } as const;
const LINK = "cursor-pointer text-muted-foreground transition-colors hover:text-foreground";

export function SkillsPanel({ api }: { api: ChatApi["api"] }) {
  const [data, setData] = useState<Skills | null>(null);
  const [scope, setScope] = useState<Scope>("me");
  const [armed, setArmed] = useState<string | null>(null);   // a remove asks twice
  const file = useRef<HTMLInputElement>(null);
  const load = () => api("/skills", { silent: true }).then((r) => r.json()).then(setData).catch(() => setData(null));
  useEffect(() => { load(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  const act = (p: Promise<unknown>) => p.catch(() => {}).finally(load);   // a failure is the api's toast
  const into = data?.scopes.includes(scope) ? scope : data?.scopes[0];
  const download = async (s: Skill) => {
    const a = Object.assign(document.createElement("a"), { download: `${s.name}.zip` });
    a.href = URL.createObjectURL(await (await api(`/skills/${s.name}/download`)).blob());
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <>
      <div className="mb-5 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="hidden text-lg font-semibold text-foreground sm:block">{t("skills")}</h2>
          <p className="text-sm text-muted-foreground">{t("skillsSub")}</p>
        </div>
        {into && (
          <div className="flex shrink-0 items-center gap-2">
            {data!.scopes.length > 1 && (
              <select value={into} onChange={(e) => setScope(e.target.value as Scope)} aria-label={t("skillFor")}
                className="h-9 cursor-pointer rounded-full border border-border bg-background px-3 text-sm text-foreground outline-none">
                {data!.scopes.map((s) => <option key={s} value={s}>{t(SOURCE[s])}</option>)}
              </select>
            )}
            <button onClick={() => file.current?.click()} className="h-9 cursor-pointer rounded-full bg-foreground px-4 text-sm font-medium text-background transition hover:opacity-80">{t("addSkill")}</button>
            <input ref={file} type="file" accept=".zip,.skill" hidden onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) { track("skill_uploaded", { scope: into }); act(api(`/skills?scope=${into}`, { method: "POST", body: f })); }
            }} />
          </div>
        )}
      </div>
      {data && !data.skills.length && <p className="py-16 text-center text-sm text-muted-foreground">{t("noSkills")}</p>}
      {!!data?.skills.length && (
        <div className="divide-y divide-border rounded-2xl border border-border">
          {data.skills.map((s) => (
            <div key={s.name} className={cn("flex items-start gap-3 px-4 py-3", !s.allowed && "opacity-50")}>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <bdi className="truncate">{s.name}</bdi>
                  <span className="shrink-0 rounded-full border border-border px-1.5 py-px text-[10px] font-normal text-muted-foreground">
                    {t(SOURCE[s.source])}{s.version ? ` · v${s.version}` : ""}
                  </span>
                </p>
                <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground"><bdi>{s.description}</bdi></p>
                <div className="mt-1.5 flex gap-4 text-xs">
                  {s.source !== "dev" && <button onClick={() => download(s)} className={LINK}>{t("download")}</button>}
                  {s.manage && (
                    <button onClick={() => (armed === s.name ? act(api(`/skills/${s.name}?scope=${s.source}`, { method: "DELETE" })) : setArmed(s.name))}
                      className={cn(LINK, armed === s.name && "text-red-600 hover:text-red-600")}>{armed === s.name ? t("removeConfirm") : t("remove")}</button>
                  )}
                  {data.org_admin && (
                    <button onClick={() => act(api(`/skills/${s.name}`, { method: "PATCH", json: { allowed: !s.allowed } }))} className={LINK}>
                      {s.allowed ? t("offForEveryone") : t("onForEveryone")}
                    </button>
                  )}
                </div>
              </div>
              {s.allowed && <Switch on={s.on} onChange={(on) => act(api(`/skills/${s.name}`, { method: "PATCH", json: { on } }))} />}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
