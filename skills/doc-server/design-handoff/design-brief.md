# doc-server — Design Brief (high-fidelity redesign)

Paste this into Claude / Figma Make / your design agent, and attach the three
screenshots in this folder. It is fully self-contained.

---

## 1. What we're building

**doc-server** is a tiny local web app that serves a project's markdown docs
(plans, specs, design notes) as browsable HTML on `localhost`. An AI coding agent
writes docs into a repo's `docs/` folder; doc-server renders them so a human can
review them visually instead of scrolling raw markdown in a terminal.

It is a **read-only documentation viewer**. Think "personal, local GitBook /
Mintlify / Linear-docs," but generated automatically from a folder of `.md` files.

Key traits to honor in the design:
- **Local & fast.** Single user, localhost, no auth, no chrome-heavy SaaS framing.
- **Multi-project, multi-branch.** One server unifies every project's docs, grouped
  by project and then by git branch. URLs are `/<project>/<branch>/...`.
- **Auto-generated landing pages.** The viewer synthesizes overview pages from the
  docs it finds (diagrams + tables of contents); the user never authors these.
- **Light & dark.** Must look intentional in both color schemes.

## 2. Information architecture (4 screen types)

```
Root  (/)                      → lists every project; "how it works" + project map
 └─ Project  (/<project>/)     → lists the branches of one project
     └─ Branch  (/<project>/<branch>/)
                                → THE core screen: structure diagram of the docs +
                                  one summary card per document with its table of
                                  contents (links jump into the doc at a heading)
         └─ Document  (/<project>/<branch>/<doc>.html)
                                → rendered markdown reader (GitHub-style), with a
                                  back link and the same left sidebar
```

A persistent **left sidebar** appears on every screen: a project list where each
project expands to show its branches; the active branch/doc is highlighted.

## 3. Current state (see attached screenshots)

The current build is functional but visually plain — system fonts, flat cards, a
boxed Mermaid diagram, minimal hierarchy. The three screenshots are the current
implementation:

- `01-current-root-overview.png` — root: sidebar + "How it works" diagram + project map + project tiles.
- `02-current-branch-index.png` — branch: "Structure" diagram + per-document cards each listing a table of contents.
- `03-current-document-page.png` — a document page (markdown still loading in the shot; shows the shell, active-branch highlight in the sidebar, and "← back to index").

> Note: in the screenshots the Mermaid diagrams and markdown render as raw text
> because the JS libraries were firewalled in the capture environment. In the real
> app they render as proper diagrams and formatted markdown. Design for the
> rendered result, not the raw text.

## 4. What we want from the redesign

Make it **high-fidelity, modern, and polished** — a tool a developer would be happy
to keep open all day. Specifically:

1. **Strong visual hierarchy & typography.** A real type scale, a refined font
   (e.g. Inter / Geist for UI, a mono for code/paths). Generous, deliberate spacing.
2. **A proper design system.** Color tokens (light + dark), spacing scale, radius,
   elevation, semantic roles (accent, muted, border, surface, success/warn). Show
   the tokens on a styles page.
3. **Refined sidebar navigator.** Clear project → branch hierarchy, search/filter
   field at top, active-state treatment, collapse affordance, branch "chips" that
   read like git branches (mono, with a branch glyph). Handle long, slash-containing
   branch names gracefully (e.g. `feat/login`, `claude/doc-server-routing-ui-osov2g`).
4. **Beautiful landing pages.**
   - Root: a hero that explains doc-server in one line, an elegant "how it works"
     pipeline diagram, and a responsive grid of project cards (with branch counts).
   - Branch: a clean structure/overview diagram treatment (the Mermaid container
     should feel designed — padding, caption, subtle background, zoom affordance),
     followed by **document summary cards**. Each card = doc title, file path (mono),
     and a compact table of contents whose entries are links. Cards should scan well
     in a multi-column grid.
5. **Excellent document reader.** Comfortable reading measure (~70ch), styled
   markdown (headings, code blocks, tables, callouts, mermaid blocks), a sticky
   in-page "On this page" TOC on the right for longer docs, breadcrumb + back at top,
   and prev/next or "back to branch" navigation.
6. **Empty / loading / not-found states.** A nice empty state ("no docs yet"), a
   skeleton/loading state for the markdown reader, and a 404.
7. **Responsive.** Sidebar collapses to a drawer on narrow widths; card grids reflow.

Tone: clean, calm, developer-focused. Reference points: Linear, Vercel/Geist docs,
Mintlify, Stripe docs, GitHub's markdown styling. Avoid heavy gradients, stock
illustration, or marketing-site flourish — this is a utility.

## 5. Deliverables requested

- A **design system / styles** frame (color tokens for light + dark, type scale,
  spacing, radii, components: sidebar item, branch chip, project card, doc summary
  card, TOC list, diagram container, breadcrumb, buttons, search field).
- High-fidelity frames for all four screen types, in **both light and dark**:
  1. Root overview
  2. Project index
  3. Branch index (the hero screen — give this the most love)
  4. Document reader (with right-hand "On this page" TOC)
- A narrow/responsive variant of the branch index showing the collapsed sidebar.

## 6. Hard constraints (so the design stays implementable)

- Rendered client-side from static HTML + a bit of JS. Realistic to build with plain
  CSS — no native-app-only effects. Markdown via `marked`, diagrams via `mermaid`,
  base styling can extend `github-markdown-css`.
- All assets are vendored/local or from a CDN; assume the diagram and markdown
  rendering already work — design the *container and chrome* around them.
- Read-only: no editing, comments, or auth UI.
- Content is whatever the repo contains; design must tolerate 1 doc or 50, short or
  very long branch names, and deeply nested doc folders.

## 7. Real sample content (use verbatim for fidelity)

- Project: `skills` → branch: `claude/doc-server-routing-ui-osov2g`
- Documents in that branch:
  - `docs/superpowers/plans/2026-06-25-doc-server.md` — "doc-server Implementation Plan"
  - `docs/superpowers/specs/2026-06-25-doc-server-design.md` — "doc-server skill — design"
  - `docs/superpowers/plans/2026-06-25-doc-server-routing-ui.md` — "doc-server — routing fix, branch naming & UI refresh"
- Example TOC for a doc: Purpose · Goals · Non-goals · Architecture · Identity
  resolution · Freshness model · Server & port behavior · Testing strategy
- "How it works" pipeline (for the root diagram):
  `docs/**/*.md → serve.py / SessionStart hook → resolve identity (project + git
  branch) → registry.json → sync (markdown → HTML) → ~/.claude/doc-server/<project>/<branch>/
  → localhost viewer`, with a "live re-sync on each page request" loop back to sync.
