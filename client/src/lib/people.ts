// From the person's id, so their colour is the same in every design and for everyone.
const PEER_COLORS = ["#e5484d", "#0090ff", "#30a46c", "#f5a524", "#8e4ec6", "#f76b15", "#00a2c7", "#d6409f"];

export function peerColor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return PEER_COLORS[h % PEER_COLORS.length];
}

// The people of the organisation the app is in, by account id, for naming who made a change (a
// design's history). Set by the app as it renders, like the workspace header: the sign-in token
// carries no names, but the organisation's member list does.
let names = new Map<string, string>();

export function setPeople(people: { id: string; name: string }[]) {
  names = new Map(people.filter((p) => p.id && p.name).map((p) => [p.id, p.name]));
}

export function personName(id: string | undefined): string | undefined {
  return id ? names.get(id) : undefined;
}

// ---- Who an app is used by: cycls.ctx.user and cycls.people() ----
// The signed-in person and the active workspace's members, as an app is given them: id, name, role and a
// picture, never an email (an app can write what it is given into data the whole workspace reads). Set by
// the app as it renders, like the names above.

export interface Person { id: string; name?: string; image?: string; role?: string; you?: boolean }
export interface OrgPerson { id: string; name: string; image?: string; admin?: boolean }
export interface Roster {
  me: { id: string; name?: string; image?: string };
  // The active workspace; none on an account without an organisation.
  workspace?: { id: string; type: string; builtin?: string; role?: string | null } | null;
  org: OrgPerson[];   // the organisation's members, every page loaded
  members?: (workspaceId: string) => Promise<{ user_id: string; role: string }[]>;
}

const ROSTER_MS = 60_000;
let roster: Roster | null = null;
let cached: { key: string; at: number; people: Promise<Person[]> } | null = null;

export function setRoster(r: Roster | null) { roster = r; }

const team = (r: Roster) => r.workspace?.type === "team";
const myRole = (r: Roster) => r.workspace?.role || (team(r) ? undefined : "owner");
const clean = (p: Person): Person =>
  Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined && v !== "")) as unknown as Person;

/** Who is viewing, as an app is told at its start: id, name and role. Their picture comes with people(). */
export function viewer(): Person | null {
  return roster?.me.id ? clean({ id: roster.me.id, name: roster.me.name, role: myRole(roster) }) : null;
}

/** The workspace's members, the viewer marked `you`. Personal: the viewer alone. General: the organisation but
 *  whom an admin took out (an org admin cannot be). Another team workspace: its member rows, and the viewer
 *  even without one, since an org admin reaches every team workspace. */
export async function listPeople(r: Roster): Promise<Person[]> {
  const me: Person = { id: r.me.id, name: r.me.name, image: r.me.image, role: myRole(r), you: true };
  const ws = r.workspace;
  if (!ws || !team(r) || !r.members) return [clean(me)];
  const rows = await r.members(ws.id);
  const known = new Map(r.org.map((m) => [m.id, m]));
  let out: Person[];
  if (ws.builtin) {
    const gone = new Set(rows.filter((m) => m.role === "excluded").map((m) => m.user_id));
    out = r.org.filter((m) => m.admin || !gone.has(m.id))
      .map((m) => ({ id: m.id, name: m.name, image: m.image, role: m.admin ? "admin" : "editor" }));
  } else {
    out = rows.filter((m) => m.role !== "excluded").map((m) => {
      const o = known.get(m.user_id);
      return { id: m.user_id, name: o?.name, image: o?.image, role: m.role };
    });
  }
  const i = out.findIndex((p) => p.id === me.id);
  if (i < 0) out.unshift(me);
  else out[i] = { ...out[i], name: me.name || out[i].name, image: me.image || out[i].image, role: me.role || out[i].role, you: true };
  return out.map(clean);
}

/** listPeople with each picture made a data: URL; one look a minute per workspace. */
export function workspacePeople(): Promise<Person[]> {
  const r = roster;
  if (!r?.me.id) return Promise.reject(new Error("nobody is signed in"));
  const key = `${r.me.id}|${r.workspace?.id ?? ""}|${r.org.length}`;
  if (!cached || cached.key !== key || Date.now() - cached.at > ROSTER_MS) {
    const people = listPeople(r).then((list) => Promise.all(list.map(async (p) => clean({ ...p, image: await face(p.image) }))));
    const entry = { key, at: Date.now(), people };
    cached = entry;
    people.catch(() => { if (cached === entry) cached = null; });   // a failed look is not kept
  }
  return cached.people;
}

// A picture as a small data: URL. The app's page may load no image from the network, so a link would show
// nothing; the chat page reads it (Clerk's image host allows that) and draws it 64 px square. One try a URL.
const faces = new Map<string, Promise<string | undefined>>();

export function face(url?: string, size = 64): Promise<string | undefined> {
  if (!url || !url.startsWith("https://")) return Promise.resolve(undefined);
  let got = faces.get(url);
  if (!got) {
    got = (async () => {
      try {
        const res = await fetch(url, { credentials: "omit" });
        if (!res.ok) return undefined;
        const bmp = await createImageBitmap(await res.blob());
        const c = document.createElement("canvas");
        c.width = c.height = size;
        const s = Math.min(bmp.width, bmp.height);
        c.getContext("2d")?.drawImage(bmp, (bmp.width - s) / 2, (bmp.height - s) / 2, s, s, 0, 0, size, size);
        bmp.close?.();
        const out = c.toDataURL("image/webp", 0.85);
        return /^data:image\/(webp|png);base64,./.test(out) ? out : undefined;
      } catch {
        return undefined;
      }
    })();
    faces.set(url, got);
  }
  return got;
}
