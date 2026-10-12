# Prior art, bucket 4 - merge-conflict prediction and semantic merge tooling

Fetched 2026-10-12 with `/home/rk/Projects/priorart.py` (GitHub API via `gh auth token`), plus
crates.io / npm / PyPI / Codeberg registry APIs, official git docs, and local experiments in a
scratch repo. Every star count and date below was returned by `pa.repo()` / a registry API on
2026-10-12 unless marked otherwise. Nothing is quoted from a search snippet.

**Local environment fact that matters:** the git on this machine is **2.25.1** (`git version 2.25.1`,
`/usr/bin/git`). `git merge-tree --write-tree` does not exist there - it fails with
`fatal: unknown rev --write-tree`. Only the deprecated three-argument form is present
(`usage: git merge-tree <base-tree> <branch1> <branch2>`).

Two columns are added on top of the brief's five, because the task requires them for every row:

- **granularity** = FILE / HUNK (line-range) / SYMBOL-AST / none
- **when** = BEFORE merge (dry run, static) or DURING merge

| name | URL | what it does | granularity | when | overlap | what it does NOT do that we do |
|---|---|---|---|---|---|---|
| `git merge-tree --write-tree` (git >= 2.38) | https://git-scm.com/docs/git-merge-tree | Real three-way merge (rename detection, recursive ancestor consolidation) computed entirely in object space: "Perform merge without touching index or working tree". Exit 0 clean / 1 conflicted. `--name-only` gives conflicted paths, `-z --messages` gives typed conflict records. | FILE-level (conflicted file info is `<mode> <object> <stage> <filename>`). No line ranges, no symbols. Conflict hunks exist only inside the toplevel tree blob or in free-text messages the docs call "non-stable strings that should not be parsed by scripts". | BEFORE merge (true dry run, read-only) | **partial** | Cannot see a dirty working tree or index (docs: "does not read from or write to either the working tree or index"). No session/agent attribution. No pairwise-over-N-branches matrix, no human/agent warning channel, no functional brief. Needs git >= 2.38 (2022-10-02): the git on this machine is 2.25.1 and rejects it (`fatal: unknown rev --write-tree`). |
| `git merge-tree <base> <b1> <b2>` (deprecated `--trivial-merge`) | https://git-scm.com/docs/git-merge-tree | Old plumbing mode. Locally reproduced on git 2.25.1: prints `changed in both` + the three blob OIDs + a pseudo-diff containing `+<<<<<<< .our` markers. | FILE-level + raw conflict-marker text. Exit status is 0 even for a conflicted merge (verified locally), so it cannot be used as a gate. | BEFORE merge (dry run), but deprecated | **partial** | Deprecated in favour of `--write-tree`; no exit-status signal; unparseable pseudo-diff; same committed-trees-only limitation. |
| `git merge --no-commit --no-ff` + `git merge --abort` | https://git-scm.com/docs/git-merge | The classic manual dry run. Locally reproduced: exit 1, `UU f.txt` in `git status --porcelain`, `git diff --name-only --diff-filter=U` lists the file, `git ls-files -u` shows stages 1/2/3, `git diff --check` reports `f.txt:3: leftover conflict marker`. | FILE-level for detection (unmerged stages); line-level only indirectly, via conflict-marker lines. | DURING merge (it is a real merge that stops before the commit) | **partial** | Mutates index + working tree, so it is unsafe in the shared dirty tree we target. Git itself warns: "if there were uncommitted changes when the merge started ... `git merge --abort` will in some cases be unable to reconstruct the original (pre-merge) changes. Therefore: Warning: Running git merge with non-trivial uncommitted changes is discouraged". One merge at a time, one pair at a time, no attribution. |
| `git rerere` | https://git-scm.com/docs/git-rerere | "Reuse recorded resolution of conflicted merges" - records conflicted automerge result + human resolution, replays it later. Off by default (`rerere.enabled`). | Per-hunk preimage hash (not a report; a cache). | DURING merge only (needs a real conflict to record/replay) | **none** | Pure memoisation of past resolutions. Zero prediction, zero cross-session visibility, no notion of who is working where. |
| `git merge-base --is-ancestor` / `git merge-base` | https://git-scm.com/docs/git-merge-base | "finds the best common ancestor(s) between two commits to use for a three-way merge"; `--is-ancestor` is a pure ancestry test. | Commit-graph only. Zero conflict information. | BEFORE merge, but tells you nothing about collisions | **none** | Divergence/ancestry only. Two branches can be non-ancestral and perfectly orthogonal, or ancestral and still conflict after a rebase; it cannot distinguish these. |
| `git diff --check` | https://git-scm.com/docs/git-diff | "Warn if changes introduce conflict markers or whitespace errors ... Exits with non-zero status if problems are found." Verified locally: reports `f.txt:3: leftover conflict marker` at line granularity (exit 2). | Line-level, but only for markers already written into the tree. | DURING/AFTER a merge (post-hoc hygiene check) | **none** | Detects markers that already exist; does not predict that a merge will produce them. No cross-branch analysis. |
| `git status --porcelain` / `git ls-files -u` | https://git-scm.com/docs/git-status | "Give the output in an easy-to-parse format for scripts ... will remain stable across Git versions". The only stable machine-readable view of a dirty tree; `UU`/`AA` codes expose unmerged paths. | FILE-level (paths + staged/unstaged status). No line ranges. | BEFORE merge (observation only) | **partial** | This is the raw material our tool consumes, not a competitor: it says nothing about which other branch/session touches the same lines, and nothing about what the edit means. |
| `git diff -U0` hunk-header intersection (DIY primitive, not a tool) | https://git-scm.com/docs/git-diff | git exposes per-side hunk ranges (`@@ -a,b +c,d @@`) but never intersects them. Verified locally on git 2.25.1 with stdlib Python: featA ranges `[(3,3)]`, featB `[(3,3),(7,7)]`, intersection `[((3,3),(3,3))]` - i.e. hunk-level collision detection is ~20 lines of stdlib on top of `git diff -U0 --format= BASE..ref`. | HUNK/line-range-level (once you do the intersection yourself). | BEFORE merge, read-only, works on old git | **partial** | git ships the primitive and ships none of the product: no pairwise matrix, no dirty-tree-vs-branch comparison, no attribution, no warning surface. This gap is exactly what our tool fills. |
| Mergiraf | https://codeberg.org/mergiraf/mergiraf | Verified description: "A syntax-aware git merge driver for a growing collection of programming languages and file formats." Docs: "Configure Git to use Mergiraf instead of its default merge heuristics. This will enhance git merge, revert, rebase, cherry-pick and more." Rust, GPLv3, on crates.io as `mergiraf` ("A syntax-aware merge driver for Git", 23,447 downloads, updated 2026-09-26). Not on PyPI (404). | SYMBOL/AST-level (tree-sitter syntax trees), used to RESOLVE. | DURING merge (it is a git merge driver; invoked per conflicted file) | **partial** | No prediction at all - it never runs before a merge and never reports "these two lines of development will collide". No worktree/session awareness, no dirty-tree splitting, no agent surface. (Owner note: the GitHub `rgwood/mergiraf` URL 404s; canonical home is the Codeberg org `mergiraf`, created 2024-10-31.) |
| Spork (ASSERT-KTH / KTH) | https://github.com/ASSERT-KTH/spork | Verified description: "AST-based structured merge tool for Java, fully Git compatible" + TSE 2022 paper DOI. README: "Spork is an AST based structured merge research tool for Java ... instead of merging Java files by raw text, it resolves the abstract syntax trees and merges based on them". Built on Spoon + GumTree, 3DM algorithm. Owner is `ASSERT-KTH`, NOT jw3/spacejam (both 404). | SYMBOL/AST-level (Java only). | DURING merge - invoked as `java -jar spork.jar Left.java Base.java Right.java` on three files. | **partial** | Research tool, Java only, no prediction, no pre-merge mode, no multi-agent awareness. Its own README now says: "If you are looking for a production ready tool for AST-based GIT merge, we recommend mergiraf." |
| weave (Ataraxy-Labs) | https://github.com/Ataraxy-Labs/weave | Verified description: "Entity-level git merge driver. Resolves false conflicts git invents when independent agents edit the same file." tree-sitter entities (functions/classes/keys), 38 languages, MCP server. Crucially it also ships a pre-merge dry run: `weave preview <branch> [--file <path>]` - "What would merging this branch look like? Nothing is written", printing e.g. "src/api.ts - 1 conflict(s) / x function process: both modified" and "Merge would be clean". | SYMBOL/ENTITY-level (function/class/key), plus per-file summary. | BOTH: `weave preview` is a BEFORE-merge dry run; `weave setup/land/explain/check` are DURING-merge. | **high** | Pairwise branch-vs-branch only, on committed refs: no dirty-working-tree input, no N-worktree matrix, no session/agent attribution ("which session touched this"), no splitting one mixed dirty tree into per-feature branches, no grounded functional brief. Requires installing a Rust binary and configuring git to use weave as a merge driver. |
| SemanticMerge (Plastic SCM / Unity DevOps) | https://www.plasticscm.com/ | Commercial AST/semantic merge tool; real prior art - the ecosystem of external parser plugins is verifiable on GitHub (`andremussche/SemanticMergeDelphi` 16*, `sageserpent-open/SemanticMergeScalaPlugin` 10*, `ismtabo/SemanticMergePythonPlugin` 4*, `jriquelme/SemanticMergeGO` 2*, `darklyons/SemanticMergePerl` 2*). | SYMBOL/AST-level via per-language parser plugins. | DURING merge (interactive 3-way merge tool). | **partial** | A GUI merge tool for humans resolving an existing conflict. No prediction, no CLI/agent surface, no session awareness. Status caveat: `semanticmerge.com` now serves a casino spam page (verified 200 + content), and plasticscm.com states "Plastic SCM was acquired by Unity in 2020 and is now a part of Unity DevOps" - the standalone product page is gone. |
| git-imerge | https://github.com/mhagger/git-imerge | Verified description: "Incremental merge for git". Decomposes one big merge into a grid of small merges, records progress, and reports which sub-merges conflict. | FILE-level per sub-merge (it drives real merges). | DURING merge (it is a merge executor with resumable state). | **none** | It discovers conflicts by actually merging, incrementally. No pre-merge prediction, no dirty tree, no sessions, no agent warning. Last pushed 2024-07-17 (dormant). |
| tree-sitter merge stubs and one-day AST merge drivers | https://github.com/koterpillar/tree-sitter-merge | A real but empty prior-art cluster: `koterpillar/tree-sitter-merge` (0*, README is two lines: "Resolve merge conflicts with tree-sitter / Status: Experimental" plus two paper links), `gaurvinayak/semantic-merge` (0*, "Structural, AST-aware 3-way merge for Git - resolve false conflicts ... (tree-sitter)"), `haianhace123/codecompass` (0*, "Git merge conflict predictor using AST analysis - detect logical conflicts before you merge"), plus ~8 similar 0-star 2026 repos from hackathons. | Claimed SYMBOL/AST-level; several claim BEFORE-merge prediction. | Mixed; mostly DURING-merge drivers, with prediction claimed but not demonstrated. | **partial** | No users, no releases, no tests, no evidence the hunk/symbol intersection works at scale. They confirm the idea is in the water; none is a shipped tool. (Also: `nordmerge`, `merge-facet`, `piquant` do not exist as merge tools - see "Could not verify".) |
| Grove (NathanDrake2406/grove) | https://github.com/NathanDrake2406/grove | Verified description: "Cross-worktree conflict intelligence for git. Detects file, hunk, symbol, dependency, and schema overlaps between parallel workstreams before merge time." README: "Grove watches your git worktrees, continuously analyzes pairwise overlaps, and tells you which branches will conflict before you merge. Perfect for your multi-agents working in parallel worktrees ;)". Five scored layers (File=yellow, Hunk="Edits land in overlapping line ranges"=red, Symbol=red, Dependency=black, Schema=yellow). `grove check` exits 1 with one-liners on stderr; `--json`; ships a Claude Code PostToolUse hook that runs `grove check` after every Edit/Write; ships a GitHub Action that posts a PR-vs-PR conflict matrix. Source-verified: `compute_hunk_overlaps()` intersects `LineRange{new_start..new_start+new_lines-1}` with a proximity threshold, and `worktree_status()` shells out to `git status --porcelain=v1 -z` so dirty files are folded into the changeset (tests assert "dirty file should have diff hunks"). | FILE + HUNK/line-range + SYMBOL + dependency + schema, scored per branch pair. | BEFORE merge, read-only, and dirty-tree aware. | **high** | This is the closest thing to our collision detector. What it does not do: (a) attribute edits to sessions/agents - its unit is the worktree/branch, so five sessions sharing ONE dirty worktree are invisible to it; (b) split one mixed dirty tree into per-feature branches; (c) produce a grounded functional brief of what is being built elsewhere; (d) stay dependency-free - it is a Rust workspace (5 crates) + daemon + SQLite + tokio + tree-sitter, installed via brew/npm/cargo. Our hunk detection is a subset of its hunk detection; our value has to be the session layer, the single-shared-worktree model, and stdlib-only operation. |
| agent-semaphore (alwh1te) | https://github.com/alwh1te/agent-semaphore | Verified description: "Coordination layer for parallel coding agents: intent-carrying claims, write-time enforcement, merge-tree conflict radar, and a test-gated landing queue". README ships `asem radar` = "conflicts between worktrees, before any commit", implemented as "Snapshots of *dirty* worktrees taken through a temporary index (never mutating the working tree), compared pairwise with `git merge-tree --write-tree`", statuses CLEAN/TEXTUAL/STRUCTURAL/HEAVY, plus a PreToolUse hook that denies/writes a warning "at the moment of writing" naming the holder, its intent and branch. | FILE-level conflict verdict from merge-tree (textual vs structural classes), plus scope claims at path granularity. | BEFORE merge and BEFORE commit (dirty snapshots), with a write-time warning. | **high** | Claims/leases + landing queue, not observation: it requires agents to claim scopes and to install hooks; it does not passively discover sessions that never opted in, does not attribute a pre-existing mixed dirty tree to sessions, does not split it into per-feature branches, and does not generate a functional brief. No hunk/line-range intersection (verdict comes from merge-tree, so file-level). Needs Python 3.12 + uv install + SQLite state. 0 stars, single commit day (2026-08-18). |
| git-collision (AshishBagdane) | https://github.com/AshishBagdane/git-collision | Verified description: "Predict merge conflicts before they happen, directly from the command line." README documents a three-layer pipeline: "1. File Overlap ... 2. Line Range Overlap - checks whether the exact lines edited actually intersect (max(startA,startB) <= min(endA,endB)) 3. Merge Simulation - runs git merge-tree to confirm real conflict markers would appear", with `--json`, exit 1 on conflicts, and a `make hook` pre-push hook. JSON shows `localRanges`/`remoteRanges`/`author`. | FILE + HUNK/line-range, confirmed by merge-tree. | BEFORE merge (pre-push hook). | **high** | Same shape as our detector but scoped to "you vs origin/main": one base branch, one author per side (from blame), no session/agent concept, no multi-branch matrix, no dirty-tree-vs-multiple-sessions model, no functional brief, no merge planning. 0 stars, created and last pushed 2026-03-12 (single day), Go binary, README install path still says `your-org` - i.e. not shipped. |
| mergesage (jay-tank) | https://github.com/jay-tank/mergesage | Verified description: "Predict which git branches will conflict with a base branch before you merge - read-only, no merge attempted, optional AI merge-order advice." README: it replaces the manual `git merge --no-commit --no-ff` / `--abort` loop with "git's own `merge-tree` plumbing ... across every branch at once", ranked by conflict count, `--json`, and a test asserting `git status`/`HEAD` are byte-identical after a scan. | FILE-level (conflicting file counts per branch). No hunk ranges. | BEFORE merge, read-only. | **partial** | Exactly the "git merge-tree as a pre-flight scanner" pattern, but stops at file granularity: no hunk/line-range overlap, no dirty tree, no sessions, no brief, no integration planning. 0 stars, created/pushed 2026-07-23, not published to PyPI (404). |
| grit (rtk-ai) | https://github.com/rtk-ai/grit | Verified description: "Git for AI agents - zero merge conflicts, any number of parallel agents, same codebase". README: "Grit locks at the function level (AST), not the file level (lines). Different functions in the same file never conflict" - agents claim functions, a second claim on the same function is blocked. | SYMBOL/function-level claims (prevention), not conflict prediction. | BEFORE the edit (claim/lock), so conflicts are designed away rather than reported. | **partial** | Opt-in locking: an agent that never claims simply conflicts. No passive observation of existing sessions, no reporting of what is colliding today, no dirty-tree splitting, no brief. Tied to the rtk-ai stack. 118 stars, last pushed 2026-06-14. |
| radar (Jake-Network) and DriftWatch (Vignesh-P-C) | https://github.com/Jake-Network/radar | radar: "Catch broken merges between parallel AI coding agents (Claude Code, Codex, cmux, Orca, git worktree). Combines worktree branches, checks conflicts and contract breaks, runs affected tests. Local CLI + MCP server." DriftWatch (https://github.com/Vignesh-P-C/DriftWatch): "Real-time semantic conflict detection across parallel git worktrees - catches breaking changes between concurrent human and AI coding agents before they hit merge." | Claimed conflict + "contract break" detection across worktrees; granularity not demonstrated (no hunk-range evidence in the repos). | BEFORE merge (claimed), real-time. | **partial** | Both are 2-star, days-old projects (radar created 2026-10-09, pushed 2026-10-11; DriftWatch created 2026-08-03, pushed 2026-09-15). Neither shows session attribution inside one shared dirty worktree, dirty-tree splitting, or a grounded brief. Treat as directional evidence that this niche is being colonised, not as shipped competition. |
| The 2026 "predict conflicts before merge" long tail | https://github.com/varanasi-ramya/MergeMaven | A dense cluster of small tools all aiming at the same sentence: MergeMaven - "Predicts which PRs will clash, recommends merge order, and verifies predictions with real git simulations" (1*, 2026-10-11); BranchRift - "read-only Git integration risk checks for branch divergence, same-path collisions, ownership gaps" (2*, 2026-09-28); arcforge - "conflicts are predicted before merge" for agent swarms (0*, 2026-10-12); merge-queue-readiness (0*, 2026-09-26); `ritesh31/claude-pre-merge-conflict-predictor` - "Claude Code skill: predict merge conflicts before opening a PR by checking file overlap against other open PRs/branches" (1*, 2026-08-03); plus ~10 ML "merge conflict predictor" student repos. | Mostly FILE-level overlap vs open PRs (the Claude skill is explicitly file-overlap only); ML ones predict per-PR probability, not locations. | BEFORE merge, but almost all of them need the GitHub API and pushed branches. | **partial** | None is local-only: they need a PR or a pushed branch, so a session sitting on uncommitted work in a shared tree is invisible. None attributes to sessions, none splits a dirty tree, none produces a grounded brief. Individually negligible; collectively they mean "predict merge conflicts before you merge" is no longer a novel sentence to write in a README. |
| GitHub mergeability (`mergeable` / `mergeable_state`) and the PR conflict banner | https://docs.github.com/en/rest/pulls/pulls | GitHub computes mergeability server-side and exposes it on the PR. Verified live against the API on 2026-10-12 for an unmergeable open PR (ManageIQ/manageiq-rpm_build#698): `{"mergeable": false, "mergeable_state": "dirty", "rebaseable": false}`. The UI shows "This branch has conflicts that must be resolved". | FILE-level (the UI lists conflicting files; the API exposes only a boolean + state string). | BEFORE merge, but only for a pushed branch with an open PR; computed asynchronously and cached (`mergeable` is null while GitHub checks). | **partial** | Server-side, PR-scoped, requires a push, and cannot see an uncommitted shared worktree or a local branch with no PR. No hunk ranges, no session attribution, no agent-facing local warning, no cross-session brief. |
| Merge bots / merge queues: mergeable, Mergify, Bors, Dependabot, Trunk, GitHub Merge Queue | https://github.com/mergeability/mergeable | mergeable - "🤖 All the missing GitHub automation 🙂" (718*, last pushed 2024-07-29, effectively dormant). bors-ng - "👁 A merge bot for GitHub Pull Requests" (1,529*, 2024-04-04): tests each PR against main before landing, so a conflict or breakage is caught before merge. dependabot-core (5,804*, 2026-10-12) rebase/conflict handling for dependency PRs. Mergifyio/mergify is the "Mergify Community Issue Tracker" (339*, 2023-09-07) - the engine is SaaS. trunk-io/trunk-action (248*, 2026-10-05) fronts Trunk's hosted merge queue. | FILE-level conflict verdict per PR (delegated to git/GitHub), plus CI verdicts. | BEFORE merge (queue admission / try-on-merge), server-side. | **none** | All of them require pushed refs and a hosted forge, serialise merges rather than warn agents, and are blind to uncommitted work and to which agent is responsible. Nothing local, nothing hunk-level, nothing session-aware. |
| GitLab merge-request conflict status and conflict editor | https://docs.gitlab.com/api/merge_requests/ | MR API exposes `has_conflicts` ("If true, the merge request has conflicts and cannot merge. Returns false unless merge_status is cannot_be_merged") and `detailed_merge_status` ("Detailed merge status information. See merge status for a list of potential values"); `merge_status` was deprecated in GitLab 15.6 in favour of `detailed_merge_status`. | FILE-level boolean/status per MR. | BEFORE merge, server-side, after a push. | **none** | Same limits as GitHub: forge-side, MR-scoped, no local dirty tree, no hunk ranges, no sessions. (The GitLab user-docs page for the web conflict editor returned a bot-check 403 from this machine; the API page above is the verified source.) |
| Display-only diff tools: difftastic, delta, diffnav, ydiff | https://github.com/Wilfred/difftastic | difftastic - "a structural diff that understands syntax" (25,999*, 2026-10-12). delta - "A syntax-highlighting pager for git, diff, grep, rg --json, and blame output" (32,482*, 2026-10-10). diffnav - "A git diff pager based on delta but with a file tree, a la GitHub" (1,590*, 2026-10-07). ydiff - "View colored, incremental diff in workspace or from stdin, side by side and auto paged" (936*, 2026-09-30; PyPI ydiff 1.5 uploaded 2025-12-06). | Presentation only. difftastic is AST-aware for DISPLAY, not for merge or prediction. | Neither - they render a diff you already have. | **none** | Explicitly NOT conflict prediction and NOT merge tooling: no three-way merge, no cross-branch analysis, no worktree/session awareness. They are frequently confused with merge tooling in READMEs; they do not belong in the same category as our collision detector. |
| yjs (awareness protocol) | https://github.com/yjs/yjs | Verified description: "Shared data types for building collaborative software" (22,921*, 2026-10-07). CRDT shared types plus an awareness protocol that broadcasts per-user presence/cursor ranges to peers. | Character/operation-level, resolved automatically (no conflict is ever surfaced as a hunk). | AT EDIT TIME, continuously - the strongest form of "before the merge", because there is no merge. | **partial** | Requires every writer to join the same document session over a transport; it does not apply to independent git clones/branches, cannot see work that is not in the shared doc, and offers no attribution of a git working tree to sessions. Cited as the awareness-protocol prior art for our "other sessions are editing here" signal, not as a git tool. |
| ot.js (Operational-Transformation/ot.js) | https://github.com/Operational-Transformation/ot.js | npm `ot` ("Collaborative editing using operational transformation", latest 0.0.15, last modified 2022-06-23); repo 2,137*, last pushed 2026-09-25. Classic OT: transform concurrent operations against a central revision log. | Operation-level, resolved by transformation order. | AT EDIT TIME, against a server-authoritative revision. | **none** | Needs a central server and in-process adoption; no git, no branches, no files, no sessions, no prediction. Prior art for "concurrent edits are known before they collide", nothing more. |

## The question this bucket was asked, answered bluntly

**Is there an existing tool that predicts, BEFORE merging, that two lines of development will
collide at HUNK granularity, using only local git state, and reports it to a human/agent as a
warning?** Yes. Two do it today, and one more does it at file level:

1. **Grove** (`NathanDrake2406/grove`) - hunk-level line-range intersection across worktrees,
   before merge, dirty-tree aware, with a Claude Code PostToolUse hook that prints
   `[conflict] ... both branches modify processPayment() in src/shared.ts` into the agent's tool
   output after every Edit/Write. This is our collision detector, shipped.
2. **agent-semaphore** (`alwh1te/agent-semaphore`) - `asem radar` predicts conflicts between
   *dirty* worktrees before anything is committed (temporary-index snapshots + `git merge-tree
   --write-tree`), and a PreToolUse hook warns at the moment of writing. File-level verdict, not
   hunk-level.
3. **git-collision** (`AshishBagdane/git-collision`) - documents exactly our three-layer pipeline
   (file overlap -> line-range intersection -> merge-tree confirmation) with `--json` and a
   pre-push hook. 0 stars, never installed by anyone, README install path still says `your-org`.

**Does `git merge-tree` already cover our hunk-level collision detection? No - and this is the
most important technical finding in the bucket.**

- `git merge-tree --write-tree` answers "would this merge conflict, and in which files". Its
  machine-readable conflict output is `<mode> <object> <stage> <filename>` per conflicted file
  (`--name-only` reduces it to the filename). Line ranges appear only inside the merged blob or in
  the informational messages, which the docs explicitly call "non-stable strings that should not be
  parsed by scripts, and are just meant for human consumption". So: **FILE-level prediction, not
  HUNK-level.**
- It **cannot see an uncommitted dirty working tree**: "Performs a merge, but does not make any new
  commits and does not read from or write to either the working tree or index." Our headline
  scenario - five sessions editing ONE shared dirty tree - is precisely the state it cannot read.
- It **cannot attribute to sessions or agents**. It takes two revs and returns a tree. It has no
  idea who wrote what, and no concept of a session at all.
- It **needs committed trees** for both sides. A session with 40 uncommitted files has nothing to
  hand it. (agent-semaphore works around this by building a temporary index; Grove works around it
  with `git status --porcelain=v1 -z`.)
- It **needs git >= 2.38** (2022-10-02, per the git 2.38.0 release notes: "'git merge-tree' learned
  a new mode where it takes two commits and computes a tree that would result in the merge commit").
  Our own target machine runs 2.25.1 and rejects the flag outright, so a stdlib tool that depends
  on it is not portable to the environment we are actually deploying into.
- It is **pairwise and silent**: N branches means N*(N-1)/2 invocations and no reporting surface, no
  severity, no dedup, no warning channel.

What git gives us for free, and what we must build: verified locally on 2.25.1, `git diff
--no-color -U0 --format= BASE..ref` yields `@@ -1,6 +1,6 @@` headers; parsing the `+start,count`
fields for two branches gives `featA [(3,3)]`, `featB [(3,3),(7,7)]`, intersection `[((3,3),(3,3))]`
in about 20 lines of stdlib. **The hunk intersection is trivial and git deliberately does not do
it.** Our novelty therefore cannot be "we intersect hunk ranges". It has to be the combination:
sessions (not worktrees) as the unit, one shared dirty tree as the input, agent-neutral stdlib-only
delivery, grounded functional brief, and dirty-tree -> per-feature-branch splitting.

Reproduced locally (git 2.25.1, scratch repo `/tmp/b4repo`, one file, line 3 edited on both sides):

```
$ git merge-tree $BASE featA featB          # deprecated mode
changed in both
  base   100644 01f84f8... f.txt
  our    100644 0a19230... f.txt
  their  100644 0b7827e... f.txt
@@ -1,10 +1,14 @@
+<<<<<<< .our
 A3
+=======
+B3
+>>>>>>> .their
exit=0                     <-- exit status is 0 even though it conflicted

$ git merge --no-commit --no-ff featB ; echo $?
CONFLICT (content): Merge conflict in f.txt
1
$ git status --porcelain
UU f.txt
$ git diff --name-only --diff-filter=U
f.txt
$ git diff --check ; echo $?
f.txt:3: leftover conflict marker
f.txt:5: leftover conflict marker
f.txt:7: leftover conflict marker
2
$ git ls-files -u
100644 01f84f8... 1 f.txt
100644 0a19230... 2 f.txt
100644 0b7827e... 3 f.txt
```

And the warning that kills the "just dry-run a merge" approach in a shared dirty tree, quoted from
https://git-scm.com/docs/git-merge: "if there were uncommitted changes when the merge started (and
especially if those changes were further modified after the merge was started), `git merge --abort`
will in some cases be unable to reconstruct the original (pre-merge) changes. Therefore: Warning:
Running git merge with non-trivial uncommitted changes is discouraged: while possible, it may leave
you in a state that is hard to back out of in the case of a conflict."

## Notes and evidence

- **`git merge-tree --write-tree`** - https://git-scm.com/docs/git-merge-tree (HTTP 200, 2026-10-12;
  manual "last updated in 2.52.0"). NAME line: "git-merge-tree - Perform merge without touching
  index or working tree". EXIT STATUS: "For a successful, non-conflicted merge, the exit status is 0.
  When the merge has conflicts, the exit status is 1." Conflicted file info: "<mode> <object>
  <stage> <filename>". Messages: "These are non-stable strings that should not be parsed by scripts".
  Feature age: git 2.38.0 release notes (raw.githubusercontent.com/git/git/v2.38.0) - "'git
  merge-tree' learned a new mode where it takes two commits and computes a tree that would result in
  the merge commit". Local git 2.25.1 rejects `--write-tree`.
- **`git merge-tree` deprecated mode** - same page: "git merge-tree [--trivial-merge] <base-tree>
  <branch1> <branch2> (deprecated)". Local run above: prints `changed in both` + markers, exit 0.
- **`git merge --no-commit --no-ff`** - https://git-scm.com/docs/git-merge: "With --no-commit perform
  the merge and stop just before creating a merge commit ... Note that fast-forward updates do not
  create a merge commit and therefore there is no way to stop those merges with --no-commit. Thus,
  if you want to ensure your branch is not changed or updated by the merge command, use --no-ff with
  --no-commit." Plus the uncommitted-changes warning quoted above. Local run: exit 1, `UU`,
  `--diff-filter=U`, `ls-files -u` stages 1/2/3, clean after `--abort`.
- **`git rerere`** - https://git-scm.com/docs/git-rerere: "git-rerere - Reuse recorded resolution of
  conflicted merges ... recording conflicted automerge results and corresponding hand resolve results
  on the initial manual merge". "You need to set the configuration variable rerere.enabled."
- **`git merge-base`** - https://git-scm.com/docs/git-merge-base: "git merge-base finds the best
  common ancestor(s) between two commits to use for a three-way merge"; `--is-ancestor <commit>
  <commit>` is in the synopsis.
- **`git diff --check`** - https://git-scm.com/docs/git-diff: "Warn if changes introduce conflict
  markers or whitespace errors ... Exits with non-zero status if problems are found." Local run
  reports marker lines, exit 2.
- **`git status --porcelain`** - https://git-scm.com/docs/git-status: "Give the output in an
  easy-to-parse format for scripts. This is similar to the short output, but will remain stable
  across Git versions and regardless of user configuration."
- **Mergiraf** - Codeberg API `codeberg.org/api/v1/repos/mergiraf/mergiraf`: description "A
  syntax-aware git merge driver for a growing collection of programming languages and file formats",
  **458 stars**, created 2024-10-31, updated 2026-10-09, website mergiraf.org, `mirror: false`.
  GitHub `rgwood/mergiraf` and `mergiraf/mergiraf` both 404 - the project left GitHub; the top
  GitHub hit is a mirror (`qundao/mirror-mergiraf`, 63*, "backup:
  https://codeberg.org/mergiraf/mergiraf"). crates.io `mergiraf`: "A syntax-aware merge driver for
  Git", 23,447 downloads, updated 2026-09-26. PyPI: 404. mergiraf.org: "Configure Git to use
  Mergiraf instead of its default merge heuristics. This will enhance git merge, revert, rebase,
  cherry-pick and more."
- **Spork** - `pa.repo('ASSERT-KTH/spork')`: 71 stars, created 2020-01-31, pushed 2025-02-25,
  description "AST-based structured merge tool for Java, fully Git compatible
  https://doi.org/10.1109/TSE.2022.3143766". `spacejam/spork` and `jw3/spork` both 404 - the owner in
  the task brief was wrong. README: "Spork is an AST based structured merge research tool for Java",
  usage `java -jar spork.jar Left.java Base.java Right.java`, and "If you are looking for a
  production ready tool for AST-based GIT merge, we recommend mergiraf". crates.io `spork` is an
  unrelated crate ("Safe process fork.").
- **weave** - `pa.repo('Ataraxy-Labs/weave')`: **1,319 stars**, pushed 2026-10-10, description
  "Entity-level git merge driver. Resolves false conflicts git invents when independent agents edit
  the same file. ~95% red...". README command table: "`weave preview <branch> [--file <path>]` |
  What would merging this branch look like? Nothing is written", sample output "src/api.ts - 1
  conflict(s) / x function process: both modified" and "Merge would be clean (1 file(s) auto-resolved by
  weave)". Also `weave check` ("Is my conflict resolution right?"), `weave land`
  (PROVEN/VERIFIED/REFUSED gate), MCP server, jj support (`jj resolve --tool weave`).
- **SemanticMerge** - plasticscm.com (200): "Plastic SCM was acquired by Unity in 2020 and is now a
  part of Unity DevOps". semanticmerge.com now returns a casino-spam page ("Australia Online Casinos
  2025"), i.e. the product domain is dead/squatted. Real prior art is evidenced by the plugin
  ecosystem: `andremussche/SemanticMergeDelphi` 16* "Pascal parser for PlasticSCM SemanticMerge
  tool", `sageserpent-open/SemanticMergeScalaPlugin` 10*, `ismtabo/SemanticMergePythonPlugin` 4*,
  `jriquelme/SemanticMergeGO` 2*, `darklyons/SemanticMergePerl` 2*.
- **git-imerge** - `pa.repo('mhagger/git-imerge')`: **2,848 stars**, pushed 2024-07-17, created
  2013-05-01, description "Incremental merge for git". Ecosystem: `magit/magit-imerge` 34*,
  `crimaniak/git-imerge-rs` (Rust port, 2026-09-20).
- **tree-sitter stub cluster** - `koterpillar/tree-sitter-merge` 0*, pushed 2024-02-17, README is
  "Resolve merge conflicts with tree-sitter / Status: Experimental" + links to the Spork paper.
  `gaurvinayak/semantic-merge` 0*, created 2026-06-08. `haianhace123/codecompass` 0*, created
  2026-05-25, "Git merge conflict predictor using AST analysis - detect logical conflicts before you
  merge".
- **Grove** - `pa.repo('NathanDrake2406/grove')`: 13 stars, created 2026-02-20, pushed 2026-07-17,
  single contributor (195 commits), releases v0.3.0 (2026-02-23) -> v0.4.1 (2026-03-12), npm
  `@nathan2406/grove` latest 0.4.1 (2026-03-12) with description "Cross-worktree conflict
  intelligence for git". Repo tree: `crates/{grove,grove-cli,grove-daemon,grove-lib,grove-tui}`,
  `action/`, `npm/`, `docs/`. Source read: `grove-lib/src/diff.rs::compute_hunk_overlaps` builds
  `LineRange{start: hunk.new_start, end: new_start+new_lines-1}` for both sides and reports an
  overlap when `distance <= proximity_threshold`; `grove-daemon/src/git.rs::worktree_status` runs
  `git status --porcelain=v1 -z --no-renames` and `worker.rs::extract_changeset` merges those
  statuses into the committed diff (tests: `extract_changeset_includes_uncommitted_changes`,
  "dirty file should have diff hunks"). Architecture per README: daemon (double-fork), SQLite WAL,
  Unix socket NDJSON, ratatui TUI, tree-sitter symbol layer for TS/JS/Rust/Go/Python/Java/C#.
- **agent-semaphore** - `pa.repo('alwh1te/agent-semaphore')`: 0 stars, created and pushed 2026-08-18.
  README quotes: "conflict prediction before anything is committed"; Radar row: "Snapshots of *dirty*
  worktrees taken through a temporary index (never mutating the working tree), compared pairwise with
  `git merge-tree --write-tree` ... Statuses: CLEAN / TEXTUAL / STRUCTURAL / HEAVY"; "a warning at the
  moment of writing"; "Local-first: no daemon, no cloud, no account. A single SQLite file in the git
  common dir"; `asem radar  # conflicts between worktrees, before any commit`; exit code 3 =
  held/conflict/bounced.
- **git-collision** - `pa.repo('AshishBagdane/git-collision')`: 0 stars, created and pushed
  2026-03-12. README pipeline and JSON schema quoted in the table; `localRanges`/`remoteRanges`
  prove line-range granularity; `author` field is git blame, not a session id.
- **mergesage** - `pa.repo('jay-tank/mergesage')`: 0 stars, created and pushed 2026-07-23. README:
  "The manual way is `git merge --no-commit --no-ff <branch>` then `git merge --abort`, one branch at
  a time. `mergesage` runs that check - safely, read-only, via git's own `merge-tree` plumbing -
  across every branch at once and ranks them by how much conflict they'll cause." Not on PyPI (404).
- **grit** - `pa.repo('rtk-ai/grit')`: 118 stars, pushed 2026-06-14, description "Git for AI agents -
  zero merge conflicts, any number of parallel agents, same codebase". README: "Grit locks at the
  function level (AST), not the file level (lines)."
- **radar / DriftWatch** - `Jake-Network/radar` 2*, created 2026-10-09, pushed 2026-10-11;
  `Vignesh-P-C/DriftWatch` 2*, created 2026-08-03, pushed 2026-09-15. Descriptions quoted verbatim in
  the table.
- **long tail** - MergeMaven 1* (2026-10-11), BranchRift 2* (2026-09-28), arcforge 0* (2026-10-12),
  merge-queue-readiness 0* (2026-09-26), ritesh31/claude-pre-merge-conflict-predictor 1* (2026-08-03).
  Descriptions quoted verbatim. Also a separate academic/ML genre that predicts *whether* a merge
  conflicts, never *where*: `razan-ghafra/predicting-merge-conflicts` ("Deep active learning model to
  predict merge conflicts in software repositories using social and technical facts"),
  `vctoriawu/git-merge-conflict` ("Using ML to predict git merge conflicts"),
  `ward/semantic-merge-conflicts-scam2023` (SCAM 2023 paper data).
- **GitHub mergeability** - https://docs.github.com/en/rest/pulls/pulls (200) documents the
  `mergeable`, `rebaseable`, `mergeable_state` response fields. Live check on 2026-10-12 via
  `GET /repos/ManageIQ/manageiq-rpm_build/pulls/698`: `mergeable=False`,
  `mergeable_state='dirty'`, `rebaseable=False`. Found through `search/issues?q=is:pr is:unmergeable`
  (13 hits).
- **Merge bots** - `mergeability/mergeable` 718*, pushed 2024-07-29 ("🤖 All the missing GitHub
  automation 🙂"); `bors-ng/bors-ng` 1,529*, pushed 2024-04-04 ("👁 A merge bot for GitHub Pull
  Requests"); `dependabot/dependabot-core` 5,804*, pushed 2026-10-12 ("🤖 Dependabot's core logic for
  creating update PRs."); `Mergifyio/mergify` 339*, pushed 2023-09-07 ("Mergify Community Issue
  Tracker" - the engine itself is not open source); `trunk-io/trunk-action` 248*, pushed 2026-10-05.
  `trunk-io/mergequeue` does not exist (404).
- **GitLab** - https://docs.gitlab.com/api/merge_requests/ (200): `has_conflicts` - "If true, the
  merge request has conflicts and cannot merge. Dependent on the merge_status property. Returns false
  unless merge_status is cannot_be_merged."; `detailed_merge_status` - "Detailed merge status
  information. See merge status for a list of potential values."; `merge_status` "Deprecated in
  GitLab 15.6" in favour of it.
- **Display tools** - `Wilfred/difftastic` 25,999*, pushed 2026-10-12 ("a structural diff that
  understands syntax"); `dandavison/delta` 32,482*, pushed 2026-10-10; `dlvhdr/diffnav` 1,590*,
  pushed 2026-10-07; `ymattw/ydiff` 936*, pushed 2026-09-30, PyPI `ydiff` 1.5 uploaded 2025-12-06.
  None of them merges or predicts; they render.
- **yjs** - `pa.repo('yjs/yjs')`: 22,921*, pushed 2026-10-07, "Shared data types for building
  collaborative software". **ot.js** - `Operational-Transformation/ot.js` 2,137*, pushed 2026-09-25;
  npm `ot` latest 0.0.15, "Collaborative editing using operational transformation", last publish
  2022-06-23. Adjacent and also relevant as awareness prior art: `automerge/automerge` 6,656*
  (2026-10-09), `loro-dev/loro` 6,210* (2026-10-09), `josephg/ShareJS` 4,976* (dormant, 2016).

## Surprises / collisions

1. **Grove is the real threat.** It already ships the sentence we wanted to write: file + hunk +
   symbol + dependency + schema overlap, scored per branch pair, before merge, across worktrees, with
   `--json`, exit codes, a GitHub Action that posts a PR-vs-PR conflict matrix, and a Claude Code
   PostToolUse hook that feeds `[conflict]` warnings into an agent's tool output after every edit. It
   even folds uncommitted files into the changeset via `git status --porcelain=v1 -z`. Weaknesses we
   can honestly claim: 13 stars, last commit 2026-07-17, one author, Rust + daemon + SQLite + npm,
   and its unit of analysis is the **worktree**, so five sessions sharing one dirty tree are one
   anonymous blob to it. It has no session attribution, no dirty-tree -> per-feature-branch splitting,
   and no grounded functional brief.
2. **`git merge-tree --write-tree` has become the industry's pre-flight check**, and several tools
   (mergesage, git-collision, agent-semaphore, MergeMaven, arcforge) are thin wrappers around it. Any
   README claim of the form "we detect conflicts before you merge" now reads as table stakes. Our
   README must say precisely what merge-tree cannot do (dirty tree, sessions, hunk ranges, git <2.38)
   and put the claim on the session layer instead.
3. **weave's `weave preview`** is a pre-merge dry run at *entity* granularity - finer than our hunk
   level - from a 1.3k-star project pushed two days ago. If we ever claim "finest-grained pre-merge
   check", weave beats us on granularity; we beat it on scope (N sessions, dirty tree, no merge
   driver installed).
4. **The niche is saturating in 2026.** Between 2026-05 and 2026-10 at least nine new repos appeared
   whose first sentence is "predict merge conflicts before they happen" or "coordinate parallel
   coding agents". Individually they are 0-2 stars and days old; collectively they mean the *idea* is
   no longer defensible, only the *combination* is.
5. **Negative results worth recording:** `nordmerge`, `merge-facet`, and `piquant` do not exist as
   merge tools (GitHub repo search 0/irrelevant hits, GitHub code search for `merge-facet` in
   READMEs: 0 hits, Codeberg search: 0 hits, crates.io: 404 for all three; "nordmerge" code hits are
   the Nord colour theme). The GitHub user `kerollmuss` does not exist (`search/users` returns an
   empty list). `rgwood/mergiraf` 404s - Mergiraf moved to Codeberg. `spacejam/spork` and `jw3/spork`
   404 - Spork is `ASSERT-KTH/spork`.

## Could not verify

- **difft** (Wilfred's "structural diff for identifying breaking changes"): no GitHub repo
  (`Wilfred/difft` 404 on both HTML and REST), no crates.io crate, no Homebrew formula
  (`formulae.brew.sh/api/formula/difft.json` 404), and `difft.wilfred.me.uk` does not resolve from
  this machine (DNS `Name or service not known`). Its successor **difftastic** is verified and is the
  row that matters. Status: unverified, likely defunct or moved.
- **mo / `mo diff`**: no verifiable repo found (`cosmo/mo` and `Cosmo/mo` both 404; GitHub search for
  "mo diff" returns nothing relevant). Excluded rather than guessed at.
- **GitLab's web merge-conflict editor documentation page**: `docs.gitlab.com/user/project/merge_requests/resolve_conflicts/`
  returned HTTP 403 (Cloudflare bot check) from this machine, so I cite only the GitLab REST API page
  that I could fetch. The feature exists; the exact doc wording is unverified.
- **GitHub `mergeable_state` value list** (clean/dirty/blocked/behind/unstable/unknown): the docs page
  renders field descriptions client-side, so I could not extract the enumeration. I verified the
  `dirty` value empirically against a live PR instead.
- **Mergify's conflict handling**: the product is closed SaaS; only the issue-tracker repo
  (`Mergifyio/mergify`, 339*, dormant since 2023-09-07) is verifiable. No claim is made about its
  internals.
- **Trunk merge queue**: `trunk-io/mergequeue` does not exist; only `trunk-io/trunk-action` (248*) is
  verifiable. The queue's conflict behaviour is unverified.
- **SemanticMerge's current product status**: the vendor page is a squatted casino site; whether the
  tool still ships inside Unity DevOps could not be confirmed from a fetchable page.
