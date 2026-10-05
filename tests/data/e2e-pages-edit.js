// An agent's edit on the page "Story" of e2e-pages.fig, as the service compiles one: it goes to its page first.
figma.currentPage = figma.root.children.find((p) => p.name === "Story") || figma.currentPage;
const t = figma.currentPage.findOne((n) => n.name === "headline"); t.characters = "Tomorrow"; figma.currentPage.selection = [t];
