// A link that only drafts the composer, never sends (`?draft=`, cycls.com's "Make one like this"): kept as any draft
// is (cycls_draft: the signed-out home shows it, a sign-in keeps it, the chat takes it in), and the URL forgets it.
export function keepDraftFromUrl() {
  const draft = new URLSearchParams(location.search).get("draft");
  if (!draft) return;
  sessionStorage.setItem("cycls_draft", draft);
  const u = new URL(location.href);
  u.searchParams.delete("draft");
  history.replaceState(history.state, "", u.toString());
}
