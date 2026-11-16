import { describe, it, expect, afterEach } from "vitest";
import { face, listPeople, setRoster, viewer, workspacePeople, type Roster } from "../src/lib/people";

const ORG = [
  { id: "u_me", name: "Me", image: "https://img.clerk.com/me" },
  { id: "u_sara", name: "Sara", image: "https://img.clerk.com/sara" },
  { id: "u_omar", name: "Omar" },
  { id: "u_boss", name: "Boss", admin: true },
];
const roster = (workspace: Roster["workspace"], rows: { user_id: string; role: string }[] = []): Roster => ({
  me: { id: "u_me", name: "Me", image: "https://img.clerk.com/me" }, workspace, org: ORG, members: async () => rows,
});

describe("who an app is used by", () => {
  afterEach(() => setRoster(null));

  it("a personal workspace is the viewer alone", async () => {
    const alone = [{ id: "u_me", name: "Me", image: "https://img.clerk.com/me", role: "owner", you: true }];
    expect(await listPeople(roster({ id: "u-u_me", type: "personal", role: "owner" }))).toEqual(alone);
    expect(await listPeople(roster(null))).toEqual(alone);   // an account with no organisation
  });

  it("General is the organisation but whom an admin took out, and never an org admin", async () => {
    const got = await listPeople(roster({ id: "t-shared", type: "team", builtin: "org", role: "editor" },
                                        [{ user_id: "u_omar", role: "excluded" }, { user_id: "u_boss", role: "excluded" }]));
    expect(got.map((p) => [p.id, p.role, !!p.you])).toEqual([
      ["u_me", "editor", true], ["u_sara", "editor", false], ["u_boss", "admin", false]]);
  });

  it("another team workspace is its members, and the viewer even without a row", async () => {
    const got = await listPeople(roster({ id: "t-eng", type: "team", role: "admin" },
                                        [{ user_id: "u_sara", role: "owner" }, { user_id: "u_gone", role: "editor" }]));
    expect(got).toEqual([
      { id: "u_me", name: "Me", image: "https://img.clerk.com/me", role: "admin", you: true },
      { id: "u_sara", name: "Sara", image: "https://img.clerk.com/sara", role: "owner" },
      { id: "u_gone", role: "editor" },   // no longer in the organisation: no name to give
    ]);
  });

  it("an app starts knowing the viewer, never their email or picture", () => {
    expect(viewer()).toBeNull();
    setRoster(roster({ id: "t-eng", type: "team", role: "editor" }));
    expect(viewer()).toEqual({ id: "u_me", name: "Me", role: "editor" });
  });

  it("a picture that cannot be read is left out, never sent as a link the app cannot load", async () => {
    expect(await face("http://img.example/x.png")).toBeUndefined();
    expect(await face(undefined)).toBeUndefined();
    setRoster(roster({ id: "u-u_me", type: "personal" }));
    const [me] = await workspacePeople();   // jsdom draws no image
    expect(me.id).toBe("u_me");
    expect(me.image === undefined || me.image.startsWith("data:image/")).toBe(true);
  });
});
