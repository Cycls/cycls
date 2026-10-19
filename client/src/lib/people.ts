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
