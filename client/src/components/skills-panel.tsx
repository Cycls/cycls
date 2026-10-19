// The Skills tab (docs/notes/skills.md): the list, a skill's page (overview, files, versions) and the form
// that writes one. A new skill is the person's own; sharing it with a workspace or the org is a step on its page.
import { useEffect, useRef, useState } from "react";
import { Icon } from "./icon";
import { Switch } from "./connectors-dialog";
import { TextPart } from "./parts/text-part";
import type { ChatApi } from "../hooks/use-chat";
import { t, getLang } from "../lib/i18n";
import { cn } from "../lib/utils";
import { track } from "../lib/analytics";

type Api = ChatApi["api"];
type Scope = "org" | "workspace" | "me";
type Skill = {
  name: string; description: string; source: Scope | "dev"; version: number | null; updated: string | null;
  who: string | null; yours: boolean; on: boolean; allowed: boolean; manage: boolean;
  title?: string; title_ar?: string; description_ar?: string;
};
type Page = Skill & { versions: { v: number; at: string; who: string | null }[]; files: string[] };
type View = { at: "list" } | { at: "skill"; name: string } | { at: "form"; edit?: Page };
const SOURCE = { dev: "skillBuiltIn", org: "skillOrg", workspace: "skillWorkspace", me: "skillMine" } as const;

// What people see of a skill: in Arabic, its Arabic title and description; else its title; else its own name and
// description, which are the model's.
const display = (s: Skill) => {
  const ar = getLang() === "ar";
  return { title: (ar && s.title_ar) || s.title || s.name, about: (ar && s.description_ar) || s.description };
};
const WHO = { org: "skillOrgSub", workspace: "skillWorkspaceSub", me: "skillMineSub" } as const;
const MENU = "absolute end-0 top-full z-20 mt-2 w-64 rounded-xl border border-border bg-background py-1 shadow-lg";
const ITEM = "flex w-full cursor-pointer items-center gap-2.5 px-3 py-2 text-start text-sm text-foreground hover:bg-secondary/60";
const FIELD = "w-full rounded-xl border border-border bg-background px-3.5 py-2.5 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-foreground/30";
const day = (at: string | null) => at ? new Date(at).toLocaleDateString(getLang() === "ar" ? "ar" : "en", { month: "short", day: "numeric" }) : "";
const body = (md: string) => md.replace(/^---\n[\s\S]*?\n---\n*/, "");

function Menu({ label, children }: { label: React.ReactNode; children: (close: () => void) => React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative shrink-0">
      <button onClick={() => setOpen(!open)} className="flex cursor-pointer items-center">{label}</button>
      {open && <><div className="fixed inset-0 z-10" onClick={() => setOpen(false)} /><div className={MENU}>{children(() => setOpen(false))}</div></>}
    </div>
  );
}

const Mark = () => (
  <span className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-border bg-secondary/40 text-muted-foreground">
    <Icon name="doc" className="size-5" strokeWidth={1.5} />
  </span>
);

export function SkillsPanel({ api, onAsk }: { api: Api; onAsk: (text: string) => void }) {
  const [data, setData] = useState<{ skills: Skill[]; scopes: Scope[]; org_admin: boolean } | null>(null);
  const [view, setView] = useState<View>({ at: "list" });
  const [query, setQuery] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const load = () => api("/skills", { silent: true }).then((r) => r.json()).then(setData).catch(() => setData(null));
  useEffect(() => { load(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  const act = (p: Promise<unknown>) => p.catch(() => {}).finally(load);   // a failure is the api's toast
  const own: Scope | undefined = data?.scopes.includes("me") ? "me" : data?.scopes[0];

  if (view.at === "skill" && data) return <SkillPage api={api} name={view.name} scopes={data.scopes} orgAdmin={data.org_admin}
    onBack={() => { setView({ at: "list" }); load(); }} onEdit={(edit) => setView({ at: "form", edit })} />;
  if (view.at === "form" && own) return <SkillForm api={api} edit={view.edit} scope={own}
    onDone={(name) => { load(); setView(name ? { at: "skill", name } : { at: "list" }); }} />;

  const q = query.trim().toLowerCase();
  const rows = (data?.skills ?? []).filter((s) => !q
    || [s.name, s.title, s.title_ar, s.description, s.description_ar].some((f) => f?.toLowerCase().includes(q)));
  return (
    <>
      <div className="mb-5 flex items-center gap-3">
        <h2 className="font-display hidden text-lg font-semibold text-foreground sm:block">{t("skills")}</h2>
        <div className="relative ms-auto min-w-0 flex-1 sm:max-w-xs">
          <Icon name="search" className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("searchSkills")} dir="auto"
            className="h-9 w-full rounded-full border border-border bg-background pe-3 ps-9 text-sm outline-none placeholder:text-muted-foreground focus:border-foreground/30" />
        </div>
        {own && (
          <Menu label={<span className="flex h-9 items-center gap-1.5 rounded-full bg-foreground px-4 text-sm font-medium text-background transition hover:opacity-80">
            <Icon name="plus" className="size-4" />{t("add")}<Icon name="chevron-down" className="size-3.5" /></span>}>
            {(close) => <>
              <button onClick={() => { close(); file.current?.click(); }} className={ITEM}><Icon name="upload" className="size-4 text-muted-foreground" />{t("uploadSkill")}</button>
              <button onClick={() => { close(); setView({ at: "form" }); }} className={ITEM}><Icon name="pencil" className="size-4 text-muted-foreground" />{t("createSkill")}</button>
              <button onClick={() => { close(); track("skill_create_chat", {}); onAsk(t("createSkillPrompt")); }} className={ITEM}><Icon name="star" className="size-4 text-muted-foreground" />{t("createSkillWith")}</button>
            </>}
          </Menu>
        )}
        <input ref={file} type="file" accept=".zip,.skill" hidden onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f && own) { track("skill_uploaded", { scope: own }); act(api(`/skills?scope=${own}`, { method: "POST", body: f })); }
        }} />
      </div>
      <p className="mb-4 text-sm text-muted-foreground">{t("skillsSub")}</p>
      {data && !rows.length && <p className="py-16 text-center text-sm text-muted-foreground">{q ? t("noSkillsFound") : t("noSkills")}</p>}
      <div className="divide-y divide-border">
        {rows.map((s) => (
          <div key={s.name} onClick={() => setView({ at: "skill", name: s.name })}
            className={cn("flex cursor-pointer items-center gap-3 py-3 transition-colors hover:bg-secondary/30", !s.allowed && "opacity-50")}>
            <Mark />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-foreground"><bdi>{display(s).title}</bdi></p>
              <p className="truncate text-xs text-muted-foreground">{t(SOURCE[s.source])} · <bdi>{display(s).about}</bdi></p>
            </div>
            <span className="hidden shrink-0 text-xs text-muted-foreground sm:block">{day(s.updated)}</span>
            {s.allowed && <span onClick={(e) => e.stopPropagation()}><Switch on={s.on} onChange={(on) => act(api(`/skills/${s.name}`, { method: "PATCH", json: { on } }))} /></span>}
          </div>
        ))}
      </div>
    </>
  );
}

function SkillPage({ api, name, scopes, orgAdmin, onBack, onEdit }: {
  api: Api; name: string; scopes: Scope[]; orgAdmin: boolean; onBack: () => void; onEdit: (p: Page) => void;
}) {
  const [page, setPage] = useState<Page | null>(null);
  const [tab, setTab] = useState<"overview" | "contents">("overview");
  const [v, setV] = useState<number | null>(null);   // the version being looked at; null is the one that loads
  const [path, setPath] = useState("SKILL.md");
  const [text, setText] = useState("");
  const [raw, setRaw] = useState(false);
  const [armed, setArmed] = useState(false);
  const at = v ? `?v=${v}` : "";
  const load = () => api(`/skills/${name}${at}`, { silent: true }).then((r) => r.json()).then(setPage).catch(onBack);
  useEffect(() => { load(); }, [v]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (tab === "contents") api(`/skills/${name}/file?path=${encodeURIComponent(path)}${v ? `&v=${v}` : ""}`, { silent: true })
      .then((r) => r.text()).then(setText).catch(() => setText(t("binaryFile")));
  }, [tab, path, v]);   // eslint-disable-line react-hooks/exhaustive-deps
  const act = (p: Promise<unknown>) => p.catch(() => {}).finally(load);
  if (!page) return null;
  const download = async () => {
    const a = Object.assign(document.createElement("a"), { download: `${name}.zip` });
    a.href = URL.createObjectURL(await (await api(`/skills/${name}/download`)).blob());
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const shown = v ?? page.version;
  const creator = page.source === "dev" ? "Cycls" : page.yours ? t("you") : page.who;
  const by = page.source === "dev" ? t("skillByAgent") : page.yours ? t("skillByYou") : page.who ? t("byName").replace("{name}", page.who) : "";

  return (
    <>
      <button onClick={onBack} className="mb-5 flex cursor-pointer items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <Icon name="chevron-left" className="size-4 rtl:rotate-180" />{t("skills")}
      </button>
      <div className="flex items-center gap-3">
        <Mark />
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-base font-semibold text-foreground"><bdi>{display(page).title}</bdi></h3>
          <p className="truncate text-xs text-muted-foreground">{[by, page.updated && `${t("updated")} ${day(page.updated)}`].filter(Boolean).join(" · ")}</p>
        </div>
        {page.allowed && <Switch on={page.on} onChange={(on) => act(api(`/skills/${name}`, { method: "PATCH", json: { on } }))} />}
        <Menu label={<span className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-secondary/80 hover:text-foreground">⋮</span>}>
          {(close) => <>
            {page.manage && <button onClick={() => { close(); onEdit(page); }} className={ITEM}><Icon name="pencil" className="size-4 text-muted-foreground" />{t("edit")}</button>}
            {page.source !== "dev" && <button onClick={() => { close(); download(); }} className={ITEM}><Icon name="upload" className="size-4 rotate-180 text-muted-foreground" />{t("download")}</button>}
            {page.manage && scopes.length > 1 && <>
              <p className="border-t border-border px-3 pb-1 pt-2 text-[11px] text-muted-foreground">{t("availableTo")}</p>
              {scopes.map((s) => (
                <button key={s} onClick={() => { close(); act(api(`/skills/${name}/move`, { method: "POST", json: { to: s } })); }} className={cn(ITEM, "items-start")}>
                  <Icon name="check" className={cn("mt-0.5 size-4", page.source === s ? "text-foreground" : "invisible")} />
                  <span className="flex flex-col"><span>{t(SOURCE[s])}</span><span className="text-xs text-muted-foreground">{t(WHO[s])}</span></span>
                </button>
              ))}
            </>}
            {orgAdmin && <button onClick={() => { close(); act(api(`/skills/${name}`, { method: "PATCH", json: { allowed: !page.allowed } })); }} className={cn(ITEM, "border-t border-border")}>
              {page.allowed ? t("offForEveryone") : t("onForEveryone")}</button>}
            {page.manage && <button onClick={() => armed ? api(`/skills/${name}`, { method: "DELETE" }).then(() => { close(); onBack(); }).catch(() => {}) : setArmed(true)}
              className={cn(ITEM, "border-t border-border text-red-600")}><Icon name="trash" className="size-4" />{armed ? t("removeConfirm") : t("remove")}</button>}
          </>}
        </Menu>
      </div>

      <div className="mt-5 flex gap-5 border-b border-border">
        {(["overview", "contents"] as const).map((k) => (
          <button key={k} onClick={() => setTab(k)} className={cn("-mb-px cursor-pointer border-b-2 pb-2 text-sm", tab === k ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            {t(k === "overview" ? "overview" : "contents")}{k === "contents" && <span className="text-muted-foreground"> · {page.files.length}</span>}
          </button>
        ))}
      </div>

      {tab === "overview" ? (
        <div className="mt-5 grid gap-6 sm:grid-cols-[1fr_14rem]">
          <div>
            <h4 className="mb-1.5 text-xs text-muted-foreground">{t("description")}</h4>
            <p className="text-sm leading-relaxed text-foreground"><bdi>{display(page).about}</bdi></p>
          </div>
          <dl className="h-fit space-y-3 rounded-xl bg-secondary/40 p-4 text-sm">
            <div><dt className="text-xs text-muted-foreground">{t("availableTo")}</dt><dd className="text-foreground">{t(SOURCE[page.source])}</dd></div>
            {creator && <div><dt className="text-xs text-muted-foreground">{t("createdBy")}</dt><dd className="text-foreground"><bdi>{creator}</bdi></dd></div>}
            {page.version && <div><dt className="text-xs text-muted-foreground">{t("version")}</dt><dd className="text-foreground">v{page.version}</dd></div>}
          </dl>
        </div>
      ) : (
        <div className="mt-4">
          {page.versions.length > 1 && (
            <div className="mb-3 flex items-center gap-3">
              <Menu label={<span className="flex h-8 items-center gap-1.5 rounded-full border border-border px-3 text-sm text-foreground">
                v{shown}{shown === page.version && ` · ${t("current")}`}<Icon name="chevron-down" className="size-3.5" /></span>}>
                {(close) => page.versions.map((x) => (
                  <button key={x.v} onClick={() => { close(); setV(x.v === page.version ? null : x.v); }} className={ITEM}>
                    v{x.v}{x.v === page.version && ` · ${t("current")}`}<span className="ms-auto text-xs text-muted-foreground">{day(x.at)}</span>
                  </button>
                ))}
              </Menu>
              {page.manage && v !== null && v !== page.version && (
                <button onClick={() => { api(`/skills/${name}/current`, { method: "POST", json: { v } }).then(() => setV(null)).catch(() => {}); }}
                  className="cursor-pointer text-sm text-foreground underline-offset-4 hover:underline">{t("makeCurrent")}</button>
              )}
            </div>
          )}
          <div className="grid overflow-hidden rounded-xl border border-border sm:grid-cols-[13rem_1fr]">
            <div className="max-h-[22rem] overflow-y-auto border-b border-border p-1.5 sm:max-h-[28rem] sm:border-b-0 sm:border-e">
              {page.files.map((f) => (
                <button key={f} onClick={() => setPath(f)} dir="ltr"
                  className={cn("block w-full cursor-pointer truncate rounded-lg px-2.5 py-1.5 text-start text-xs", f === path ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:text-foreground")}>
                  {f.includes("/") && <span className="text-muted-foreground/70">{f.slice(0, f.lastIndexOf("/") + 1)}</span>}{f.slice(f.lastIndexOf("/") + 1)}
                </button>
              ))}
            </div>
            <div className="min-w-0">
              <div className="flex items-center justify-between border-b border-border px-4 py-2">
                <span dir="ltr" className="truncate font-mono text-xs text-muted-foreground">/{path}</span>
                {path.endsWith(".md") && <button onClick={() => setRaw(!raw)} className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">{raw ? t("formatted") : t("raw")}</button>}
              </div>
              <div className="max-h-[28rem] overflow-y-auto px-4 py-3">
                {path.endsWith(".md") && !raw
                  ? <div className="text-sm"><TextPart text={body(text)} /></div>
                  : <pre dir="ltr" className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground">{text}</pre>}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function SkillForm({ api, edit, scope, onDone }: { api: Api; edit?: Page; scope: Scope; onDone: (name?: string) => void }) {
  const [name, setName] = useState(edit?.name ?? "");
  const [description, setDescription] = useState(edit?.description ?? "");
  const [instructions, setInstructions] = useState("");
  const [titleAr, setTitleAr] = useState(edit?.title_ar ?? "");
  const [descriptionAr, setDescriptionAr] = useState(edit?.description_ar ?? "");
  useEffect(() => {
    if (edit) api(`/skills/${edit.name}/file?path=SKILL.md`, { silent: true }).then((r) => r.text()).then((md) => setInstructions(body(md))).catch(() => {});
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  const save = () => api(`/skills/${encodeURIComponent(name)}`, { method: "PUT", json: { description, body: instructions, title_ar: titleAr, description_ar: descriptionAr, scope: edit?.source ?? scope } })
    .then((r) => r.json()).then((r) => { track("skill_written", { edit: !!edit }); onDone(r.name); }).catch(() => {});
  return (
    <>
      <h3 className="mb-5 text-lg font-semibold text-foreground">{edit ? t("editSkill") : t("createSkill")}</h3>
      <label className="mb-1.5 block text-sm text-foreground">{t("skillName")}</label>
      <input value={name} onChange={(e) => setName(e.target.value)} disabled={!!edit} placeholder={t("skillNameHint")} dir="ltr" className={cn(FIELD, "mb-4 disabled:opacity-60")} />
      <label className="mb-1.5 block text-sm text-foreground">{t("description")}</label>
      <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} placeholder={t("skillDescriptionHint")} dir="auto" className={cn(FIELD, "mb-4 resize-none")} />
      <label className="mb-1.5 block text-sm text-foreground">{t("skillNameAr")}</label>
      <input value={titleAr} onChange={(e) => setTitleAr(e.target.value)} dir="rtl" className={cn(FIELD, "mb-4")} />
      <label className="mb-1.5 block text-sm text-foreground">{t("skillDescriptionAr")}</label>
      <textarea value={descriptionAr} onChange={(e) => setDescriptionAr(e.target.value)} rows={2} dir="rtl" className={cn(FIELD, "mb-4 resize-none")} />
      <label className="mb-1.5 block text-sm text-foreground">{t("instructions")}</label>
      <textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} rows={12} placeholder={t("skillInstructionsHint")} dir="auto" className={cn(FIELD, "resize-y font-mono text-xs leading-relaxed")} />
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={() => onDone(edit?.name)} className="h-9 cursor-pointer rounded-full border border-border px-4 text-sm text-foreground hover:bg-secondary/60">{t("cancel")}</button>
        <button onClick={save} disabled={!name.trim() || !description.trim()} className="h-9 cursor-pointer rounded-full bg-foreground px-4 text-sm font-medium text-background transition hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-40">
          {edit ? t("save") : t("create")}
        </button>
      </div>
    </>
  );
}
