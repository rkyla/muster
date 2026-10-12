# Prior art

A survey of the field around `muster`, written before the README's positioning was
finalised, and deliberately kept in the repo. It refuted several claims that were
in earlier drafts of this README; those claims are gone now.

**Method.** 73 GitHub repositories plus 16 non-GitHub sources, grouped into five
buckets. Every star count and push date was re-fetched from the GitHub API on
**2026-10-12**; the raw per-bucket notes with verbatim quotes are in
`docs/priorart/bucket1.md` .. `bucket5.md`. Two items could not be verified from this machine
and are flagged as such in the text rather than cited as fact.

**This survey goes stale fast.** The space moved through roughly 40 repositories
in nine months. Re-verify before repeating any number here.

---


Survey for a CLI (Python, stdlib-only, git-based) that gives AI coding agents **cross-session awareness of the same
repository**: observe refs / worktrees / dirty files, attribute work to sessions, detect file- and hunk-level
collisions, emit a grounded brief of what is being built elsewhere, and orchestrate integration (isolated-worktree
merge plans, splitting one mixed dirty tree into per-feature branches).

**Survey date: 2026-10-12.** Method: GitHub REST search + repo API (token from `gh auth token`), PyPI JSON API,
Codeberg, and primary docs/READMEs. **Every star count and date below was returned by a repo-API call on
2026-10-12**, not copied from a snippet or from memory. Quoted text is verbatim from a fetched README, man page, or
doc file. Anything not fetchable is marked **UNVERIFIED**.

Full per-bucket detail, including ~120 further rows and raw evidence quotes, lives in `priorart_bucket1.md`,
`priorart_bucket2.md`, `priorart_bucket3.md`, `priorart_bucket5.md`.

## Read this first: the honest headline

**This space is not empty. It is crowded, and it filled up during 2026.** I found roughly 40 live projects whose
stated purpose is "several AI coding agents, one repository, stop them clobbering each other" - from a 21.8k-star
GitButler down to several 0-star repos created in the last six weeks. Four of our five headline capabilities already
have a named owner somewhere. The blunt gap analysis is near the end.

Three findings that should change the README before anything else:

1. **GitButler already documents "multiple coding agents in one workspace, no separate worktrees, each agent's commits
   routed to its session's branch", and "ask an agent to split independent work out of the current session".** That is
   our capability 5, in the official docs of a 21,798-star tool. Source: `gitbutlerapp/gitbutler-docs`,
   `content/docs/ai-agents/parallel-agents.mdx`, fetched 2026-10-12.
2. **Grove already does hunk-level pre-merge overlap prediction.** Its own table: "**Hunk** | Edits land in overlapping
   line ranges | Red (adjacent = Yellow)". That is our capability 3, verbatim. Source: `NathanDrake2406/grove` README,
   fetched 2026-10-12 (13 stars, Rust, pushed 2026-07-17).
3. **Git itself reports zero session identity for uncommitted work.** I ran this locally (git 2.25.1): three simulated
   sessions appended to three files in one worktree; `git status --porcelain=v2` returned three lines of
   `1 .M N... <modes> <sha> <sha> <path>` with no author, no session, no feature; `git blame` said
   `00000000 (Not Committed Yet ...)` for every line; `GIT_AUTHOR_NAME` was empty. **The gap is real, and it is a
   property of git, not an oversight of one vendor.** Details in `priorart_bucket3.md`.

---

## Bucket 1 - Multi-agent git coordination and worktree managers

The dominant design here is the **opposite** of ours: one worktree per agent, so sessions physically cannot collide.
Their READMEs say so out loud. A second class does share awareness, but every one of them is **cooperative** - the
other agent must install and declare something.

| name | URL | what it does | overlap | what it does NOT do that we do |
|---|---|---|---|---|
| GitButler | https://github.com/gitbutlerapp/gitbutler (21,798 stars, pushed 2026-10-11) | "The GitButler version control client, backed by Git, powered by Tauri/Rust/Svelte". Virtual branches: several active branches over ONE working directory; docs describe parallel agents committing to per-session branches and splitting independent work out of a session. | **high** | Overlap detection is delegated to the agents: "If two sessions touch the same file or generated output, have the agents call out the overlap before committing." Nothing is computed from the tree. No hunk/line-range prediction, no grounded brief, no session attribution derived from git, GUI/Tauri app not a stdlib CLI. |
| herdr | https://github.com/herdrdev/herdr (43,416 stars, pushed 2026-10-11) | "the runtime your coding agents live on" - owns agent panes; agents can spawn panes, prompt each other, wait on each other over a socket API. | **partial** | Pane-level, not repository-level. No file, hunk, or dirty-file concept. Biggest neighbour in the space; if it ever reads git it swamps us. |
| vibe-kanban | https://github.com/BloopAI/vibe-kanban (28,329 stars, pushed 2026-09-19) | Kanban front-end for Claude Code / Codex / any agent; each task runs in its own branch/worktree or remote sandbox. | **none** | Isolation strategy. No cross-session awareness, no collision concept; conflicts handled at review time. |
| cmux | https://github.com/manaflow-ai/cmux (28,106 stars, pushed 2026-10-12) | macOS terminal for AI coding agents with vertical tabs and notifications. | **none** | No repository awareness. But see `wolfiesch/cmux-control` (2 stars, pushed 2026-08-21), which adds `cmux_agents`: "lets an agent see the other agent sessions running beside it", including "whether its work overlaps the files I am about to touch" - awareness from process/pane state, not from git. |
| worktrunk | https://github.com/max-sixty/worktrunk (9,189 stars, pushed 2026-10-11) | "Worktrunk is a CLI for Git worktree management, designed for parallel AI agent workflows". | **none** | Lifecycle only. No awareness, no collision detection, no dirty-tree handling. Ships a Rust binary. |
| claude-squad | https://github.com/smtg-ai/claude-squad (8,591 stars, pushed 2026-08-20) | TUI multiplexer: each agent gets a detached session in its own worktree + tmux. | **none** | README frames the goal as isolation - each task gets its own isolated git workspace "so no conflicts". |
| cc-haha | https://github.com/NanmiCoder/cc-haha (14,970 stars, pushed 2026-10-11) | Local-first desktop workbench: multi-agent collaboration, git worktree, code diff, skills market. | **partial** | Multi-agent + worktrees + diff views, but no observed collision detection and no dirty-tree attribution; tied to its own harness. |
| Foremerge | https://github.com/naw103/foremerge (538 stars, Apache-2.0, Rust, pushed 2026-10-04) | "Catch intent conflicts before code conflicts. The open-source coordination protocol for coding agents, built above Git." Agents publish intent + semantic scope into one SQLite store inside `.git`; a deterministic detector "names the two agents, explains why their plans clash, and suggests how to split the work". | **high** | Cooperative: agents must announce. Never measures real edits, so no hunk/line-range overlap. Assumes isolated worktrees; its own status line says "coordination between machines is outside this project's scope". No dirty-tree splitting. **It beats us on one axis**: it catches semantic collisions between edits in *different* files (replace `PaymentService` vs extend `PaymentService`), which line-range overlap cannot see. |
| concord-mcp | https://github.com/Get-Concord-AI/concord-mcp (456 stars, MIT, Node, pushed 2026-10-11) | "Live messaging for coding agents": cross-harness presence, file/module claims, `start_work` reports scope overlaps before editing, stale-claim detection, follows git worktree `commondir`. | **high** | Cooperative claims, not observation; file/module granularity; needs MCP registration in every harness; no dirty-tree splitting; no grounded brief built from git facts. |
| dev-3.0 | https://github.com/h0x91b/dev-3.0 (310 stars, pushed 2026-10-11) | Fleet "mission control", one worktree per task. | **none** | README: "Nothing the agent does can collide with another task." Explicitly the anti-strategy. |
| uzi | https://github.com/devflowinc/uzi (582 stars, **last push 2025-06-04**) | CLI for running many coding agents in parallel with git worktrees. | **none** | Fan-out only; dormant. |
| gwq | https://github.com/d-kuro/gwq (473 stars, pushed 2026-10-02) | "Git worktree manager with fuzzy finder ... perfect for parallel AI coding". | **none** | Lifecycle only. |
| Long tail of worktree-per-agent managers | branchlet 501 stars (2026-04-13), coderabbitai/git-worktree-runner 1,791 (2026-09-15), nekocode/agent-worktree 280 (2026-08-25), sahithvibudhi/vibe-tree 269 (2026-07-25), owengretzinger/constellagent 216 (2026-05-05), kbrdn1/gwm-cli 146 (2026-09-28), ouijit/ouijit 175 (2026-10-11), patrickdappollonio/dux 67 (2026-10-11), ClipboardHealth/groundcrew 67 (2026-10-09), dualface/kander 82 (2026-10-11), milisp/codexia 930 (2026-10-09), vivy-company/aizen 308 (2026-08-01), iishyfishyy/operator-oss 205 (2026-10-08) | Create worktree, run project setup, launch the agent, clean up. | **none** | Same shape every time. None observes another session. Listed in full in `priorart_bucket1.md`. |
| agor | https://github.com/preset-io/agor (1,436 stars, BSL 1.1, pushed 2026-10-11) | "Multiplayer AI: Bring your team and agents together". | **partial** | Visibility is for *humans* reading a board; runs its own server/DB rather than reading git facts. |
| mcp_agent_mail | https://github.com/Dicklesworthstone/mcp_agent_mail (2,202 stars, pushed 2026-10-08) | "Asynchronous coordination layer for AI coding agents: identities, inboxes, searchable threads, and advisory" leases. | **partial** | Its own docs call the leases advisory and voluntary - exactly the gap an observation-first design fills. |
| agentlocks / agent-locks / multi-agent-kernel | https://github.com/simke9445/agentlocks (11 stars, 2026-09-07), https://github.com/luohoa97/agent-locks (0 stars), https://github.com/chaseungjoon/multi-agent-kernel (4 stars, 2026-09-28) | "Advisory file locks so multiple AI coding agents can share one Git worktree"; a markdown+YAML-under-`.git` variant; an "OS style transactional coordination kernel ... allows multiple agents to edit" one directory. | **partial** | Shared-one-worktree coordination is already a settled idea with several independent implementations, one daemonless and file-based. None observes git, computes hunk overlap, writes a brief, or splits a tree. |
| who-broke-it | https://github.com/shriyashish-mishra/who-broke-it (1 star, Go, created 2026-10-02) | "Task graph, intent and conflict detection, blast radius, verified handoffs, PR merge gate, git-native sync." One static binary, "No server. No account.", "Requires only `git` at runtime", adapters for Claude Code / Codex / Cursor / OpenCode. | **high (conceptually)** | Cooperative (commit hook stamps task+agent); overlap computed over declared task paths, not measured line ranges; `wbi start TASK-001 --worktree` = worktree-per-task; no dirty-tree splitting. Ten days old, zero traction, near-overlap concept. |
| grit | https://github.com/rtk-ai/grit (118 stars, Apache-2.0, Rust, pushed 2026-06-14) | "Git for AI agents - zero merge conflicts, any number of parallel agents, same codebase": tree-sitter function-level claims, cross-agent blocking, serialised merges, 50-agent benchmarks. | **high** | Blocking + cooperative. Refutes any "nobody does sub-file conflict arbitration for agents" sentence. |
| radar | https://github.com/Jake-Network/radar (2 stars, Python, created 2026-10-09, pushed 2026-10-11) | "Two agents. Two green branches. One broken merge. Radar catches it before you merge." Combines agent worktree branches in private git state and runs tests on the combination. Local CLI, no API key, no telemetry. | **partial** | Refutes "nobody predicts breakage before merge" - but by *executing tests on committed branches*, not by static line-range analysis of uncommitted work. |
| Conductor | https://conductor.build | **UNVERIFIED.** No GitHub org exists (`org:conductorbuild` returns nothing). Only indirect evidence: `simion/termic` (301 stars) is an "Open-source Conductor.build alternative"; `degtrdg/poverty-conductor` (4 stars) is "inspired by https://conductor.build/". | unknown | Closed-source macOS product; cannot be compared from a fetched source. Do not cite specifics. |

## Bucket 2 - Agent memory layers, coordination layers, git-aware MCP, AI attribution

This bucket mixes three different things and the README must keep them apart:
**(a)** long-term memory of past decisions (huge, orthogonal to us), **(b)** task/queue coordination between agents,
**(c)** live concurrent-edit awareness (small, brand new, and our actual competitor set).

| name | URL | what it does | overlap | what it does NOT do that we do |
|---|---|---|---|---|
| Beacon | https://github.com/a1473838623/agent-beacon (4 stars, pushed 2026-09-11) | "Real-time presence & collision-avoidance for parallel AI coding agents". Local daemon + Claude Code plugin/MCP. Injects a one-line collision warning into the agent's context *before* the edit; guards `checkout`/`reset --hard`/`stash`/`rebase`/`clean` and `add -A`/`commit -a` while another session is editing the tree. "zero dependencies, 100% local", "advisory ... fails open". | **high** | State is **self-reported** by cooperating sessions; a session without Beacon is invisible. No attribution of pre-existing dirty files, file granularity only, no hunk overlap, no grounded brief, no dirty-tree splitting. Needs a daemon; Claude Code first. |
| Traffic Control | https://github.com/andrefigueira/traffic-control (2 stars, Go, created 2026-06-28) | "AI traffic control for coding agents sharing one working tree. A same-tree alternative to git worktrees." Go daemon ("tower") + `PreToolUse` hook that grants or denies a path; `SessionStart` "injects the current board into its context, so a fresh agent immediately knows who else is working and on what". | **high** | Closest to our shared-dirty-tree premise, and it frames that use case better than anyone. But leases/claims not observation, path/glob granularity, daemon, Claude-Code-first, state not read out of git. |
| SAGE | https://github.com/muslewski/agentic-sage (4 stars, Node>=20, pushed 2026-09-22) | "Session Awareness & Guidance Engine - a passive, read-only judge for fleets of parallel AI coding sessions". Separates **touched** ("Paths the checkout has dirtied (git fact)") from **claimed** ("Paths the session *intends* to own"); `sage board`; `sage merge-brief` prints contested paths. "Zero npm dependencies". | **high** | Closest existing thing to our grounded brief. But claims are voluntary, sessions must `register`, the board is per-branch/worktree, overlap is glob-level, cannot attribute dirty files inside ONE shared tree, no splitting. |
| AgentColab | https://github.com/MeharPro/AgentColab (0 stars, Python 3.9+, pushed 2026-09-05) | "Many agents. Many humans. One repo." Coordination rides on a git ref: "no server to run for it, no account to make". "Every heartbeat publishes the files your branch has actually touched, derived from `git diff` against the merge base. Nobody has to remember to claim anything." When an agent edits a file another agent changed, "it is told once - with their branch, their stated intent, and their name". "There is deliberately no lock." Badges: dependencies-0, coordination-server-free. | **high** | The most dangerous repo in this bucket for our framing: git-derived rather than claimed, zero deps, no server. But it is **per-branch** (`git diff` vs merge base), so it cannot see two agents dirtying ONE shared working tree; file-level only; no hunk prediction; no grounded functionality brief; no dirty-tree splitting. |
| agent-semaphore | https://github.com/alwh1te/agent-semaphore (0 stars, Python 3.12+, MIT, pushed 2026-08-18) | "Coordination layer for parallel coding agents: intent-carrying claims, write-time enforcement, merge-tree conflict radar, and a test-gated landing queue. Local-first, no daemon." README: "**conflict prediction before anything is committed**"; "A single SQLite file in the git common dir is the whole rendezvous point, so every worktree of the repo sees it by construction"; "Cross-vendor by design - Claude Code hooks and MCP, Codex CLI over MCP, everyone else over a git `pre-commit` hook". | **high** | Already uses the git-common-dir-as-rendezvous trick and `git merge-tree` prediction over a temporary index. But: opt-in claims with a mandatory `reason`, file-level verdicts, worktree as the unit, no hunk line-ranges, no dirty-tree splitting. |
| Collide | https://github.com/lithometric/collidemcp (1 star, Rust, created 2026-10-02, pushed 2026-10-08) | "Run multiple AI coding agents (Claude Code, Codex, Cursor) on one repo without conflicts: live awareness, write gate, briefings, one-step pushes. Free, local, MCP + hooks." Publishes a benchmark ("12 Claude Code agents at once on one repository ... 53% fewer tokens"). | **high** | Hooks-based (cooperative), worktree-oriented, briefing is about function signatures rather than a cross-session edit map, no hunk overlap, no dirty-tree splitting. |
| git-sync-check | https://github.com/tuwulalo/git-sync-check (5 stars, pushed 2026-06-12) | Zero-dependency bash/PowerShell pre-flight run from a SessionStart/UserPromptSubmit hook: prints `ahead/behind/dirty` counts, the dirty file list, active leases and worktree conflicts, and teaches the model to classify **foreign uncommitted files** ("a parallel session may be mid-work - don't stage, don't revert"). | **partial** | Sees foreign dirty files but cannot say *which* session made them; no hunk overlap, no brief of functionality, no merge plan, no splitting. Read-and-preach only. |
| Lease/claim/presence micro-cluster | dibs https://github.com/polymatx/dibs (2 stars, 2026-10-06); fencepost `ritaprieto900/fencepost`; Watchbill `Sovereign-Labs-AU/watchbill`; shared-tree-guards `albertgilopez/claude-shared-tree-guards`; Weaver `sean35mm/weaver`; oxtail `d4j3y2k/oxtail`; Hivemind `josephhaenel/Hivemind` (1 star); standup-board `kilotronic/standup-board`; parallel-sessions `sezeryavuz/parallel-sessions` (4 stars, "Pure Bash hooks, no server, no daemon"); agents-kit `hiroyuki0504/agents-kit` ("Git-only coordination: CAS via push fast-forward on a state branch"); ONEFORALL `FreakyAdy/ONEFORALL` (5 stars); pact `xujunfeng1/pact`; worksidian `StefanOjanen/worksidian` (5 stars); agent-traffic-control `wan-huiyan/agent-traffic-control` (3 stars, 124 Claude Code skills) | Dozens of 2026 projects giving agents sharing one tree leases, claims, presence boards, briefings and destructive-op guards. Granularity ranges from path prefix up to individual function/symbol (Hivemind). | **partial** | All cooperative, all file/symbol-lease granularity. None derives the edit set from git plumbing, none predicts hunk overlap, none splits a dirty tree. **Several already match our "no daemon / no server / zero deps / git-native" pitch.** Full rows and quotes in `priorart_bucket2.md`. |
| wit | https://github.com/amaar-mc/wit (46 stars, TypeScript, pushed 2026-03-27) | "Agent coordination protocol - declare intents, lock symbols, detect conflicts before code is written." | **partial** | Symbol locks are cooperative and pre-emptive; no observation of what was actually edited; no dirty-tree handling. |
| cooperative-worktree-agents | https://github.com/pedroantonnio/cooperative-worktree-agents (1 star, Python, created 2026-09-07) | "Decentralized multi-agent coordination for Codex CLI using isolated Git worktrees, shared intent-aware ledgers, cooperative conflict resolution, and serialized staging integration." Ledger in `<git-common-dir>/codex-team/` with `tasks/ agents/ claims/ decisions/ events/ locks/`; "File and area claims are advisory, not exclusive locks"; conflicts "resolved from the intent of both tasks". | **high (conceptually)** | Same architecture instinct as ours, including the shared-common-dir trick. But declaration-based rather than observational, worktree-per-task rather than one shared dirty tree, no hunk overlap, no dirty-tree splitting, Codex-skill shaped, 1 star. |
| git-ai | https://github.com/git-ai-project/git-ai (2,829 stars, pushed 2026-10-07) | "A Git extension for tracking the AI-generated code in your repos" - every line linked to the agent, model and prompt that produced it; `git ai blame`, `git ai stats`; an open attribution standard carried in **git notes**, with vendor adoption. | **partial; high on attribution** | Post-hoc, commit-time attribution of *authored* code. Does not know what another session is editing right now, does not detect collisions, does not touch a dirty tree. **Interoperate with this standard; do not reinvent attribution.** |
| claude-mem | https://github.com/thedotmack/claude-mem (99,745 stars, pushed 2026-10-11) | "Persistent Context Across Sessions for Every Agent". | **none** | Category (a): memory of the past, not awareness of the present. State the distinction plainly; do not strawman. |
| mem0 / Letta / Basic Memory / Beads | https://github.com/mem0ai/mem0 (66,997 stars, 2026-10-09), https://github.com/letta-ai/letta (25,107 stars, 2026-09-10), https://github.com/basicmachines-co/basic-memory (4,143 stars, 2026-10-12), https://github.com/gastownhall/beads (27,813 stars, 2026-10-11) | Memory layers; "Beads - A memory upgrade for your coding agent". | **none** | None indexes the working tree or another live session. |
| brain0 | https://github.com/Brain0-ai/brain0 | "'Black box for AI-written code': passive decision graph linking every commit to the agent prompts behind it." | **partial** | Retrospective provenance, not live awareness. |

## Bucket 3 - Classic multi-session git/VCS coordination

Full version with verbatim man-page quotes and the local experiments is in `priorart_bucket3.md`.

| name | URL | what it does | overlap | what it does NOT do that we do |
|---|---|---|---|---|
| `git worktree` | https://git-scm.com/docs/git-worktree (`git/git` 63,819 stars, pushed 2026-10-12; git 2.56.0 dated 2026-09-28) | "Manage multiple working trees attached to the same repository." Linked worktrees share "everything except per-worktree files such as `HEAD`, `index`". Man page REFS section: "all pseudo refs are per-worktree and all refs starting with `refs/` are shared" (exceptions: `refs/bisect`, `refs/worktree`, `refs/rewritten`). | **partial - it is our substrate** | No session concept, no attribution of a dirty file, no collision warning, no hunk overlap, no tree splitting. Verified locally: a custom `refs/agentstate/*` ref written in one worktree is readable from another, so a git-native server-free session channel already exists and nobody standardises it. |
| `git stash` | https://git-scm.com/docs/git-stash | Offloads a dirty tree (`push -p` for selected hunks, `push -- <path>` for a path) to `refs/stash`; `git stash branch <name>` "Creates and checks out a new branch named <branchname>". | **partial** | Verified locally: `refs/stash` is shared across worktrees, so it is a cross-session channel with **zero attribution** - it can destroy another session's work as easily as protect it. `stash push -p` + `stash branch` is the manual recipe our splitter must beat on novelty, not just on convenience. |
| git hooks + reflogs | https://git-scm.com/docs/githooks | `reference-transaction` "is invoked by any Git command that performs reference updates"; `post-index-change`, `post-commit`, `post-checkout`, `post-merge` exist; hooks dir is `$GIT_DIR/hooks` (the common dir, shared by all worktrees); reflogs for `refs/*` live in the common dir. | **partial** | Records ref/index movement, not who did it and not what is uncommitted. Verified locally: branch reflogs shared across worktrees, `HEAD` reflog per-worktree. |
| `git notes` | https://git-scm.com/docs/git-notes | "Adds, removes, or reads notes attached to objects, without touching the objects themselves." Default `refs/notes/commits`. | **partial** | Attaches to committed objects only; cannot describe an uncommitted edit or a session that has not committed. |
| git-lfs file locking | https://github.com/git-lfs/git-lfs (14,542 stars, pushed 2026-10-01); `docs/man/git-lfs-lock.adoc` | `git lfs lock` "Sets the given file path as 'locked' against the Git LFS server, with the intention of blocking attempts by other users to update the given path." | **partial** | The only "declare your edit" mechanism shipped inside the git world - and it is pessimistic, server-enforced, opt-in per file, LFS-tracked files only, useless offline, blind to line ranges. |
| Jujutsu (`jj`) | https://github.com/jj-vcs/jj (31,971 stars, pushed 2026-10-11) | Auto-snapshots the working copy on almost every command; "You can have multiple working copies backed by a single repo. Use `jj workspace add`". `jj absorb` = "Move changes from a revision into the stack of mutable revisions"; `jj split` = "Split a revision in two"; `jj squash`, `jj evolog`, `jj undo`. | **partial** | **Solves the messy-history problem, not the blind-agents problem.** No session identity, no intent, no edit-time or pre-merge collision warning, no attribution, no dirty-tree-to-branches. For our exact scenario it is worse: one `@` per workspace, whole-tree snapshot on every command, a `working_copy.lock` - two agents in one workspace silently fold each other's edits into whichever change is current. |
| git-branchless | https://github.com/arxanas/git-branchless (4,133 stars, pushed 2026-10-01) | Smartlog, `git undo`, `restack`, `move`, `sync`, anonymous branching, and **speculative merges**: "git-branchless can 'speculatively' apply the operations in-memory first, without touching the working copy, and quickly abort if it turns out that they would require merge conflict resolution." | **partial; high on one narrow axis** | Pre-merge conflict prediction already exists - on **committed commits**, for **one actor**. Cannot see an uncommitted dirty tree, no session identity, no cross-harness awareness, no brief, no tree splitting. |
| Sapling | https://github.com/facebook/sapling (7,031 stars, pushed 2026-10-12) | `sl absorb`: "intelligently integrate pending changes into current stack ... Attempt to amend each pending change to the proper commit in your stack. Absorb does not write to the working copy." `sl split`: "Prompt for hunks to be selected until exhausted." | **partial** | Routes pending hunks into *existing* commits in your own stack. Does not create per-feature branches, does not know other sessions exist, split is an interactive prompt. |
| Mercurial `share` / `absorb` / `uncommit` / `commit --interactive` | docstrings in the `mercurial` 7.2.4 wheel (PyPI, uploaded 2026-08-11) | `share`: "share a common history between several working directories ... allows working on different branches or changes in parallel without the associated cost in terms of disk space" (and warns destructive operations "can result in confusing problems"). `absorb`: "use annotate information to amend modified chunks into the corresponding non-public changesets". `uncommit`: "returning the affected files to their uncommitted state". `record` is deprecated because it "has been moved into core Mercurial as `hg commit --interactive`". | **partial** | Parallel working dirs and hunk routing exist in Mercurial too; none of it is aware of another session, and absorb targets existing commits in one stack. |
| Mercurial topics | https://www.mercurial-scm.org/repo/hg/help/extension_topics | **UNVERIFIED.** mercurial-scm.org and heptapod both serve an Anubis anti-bot challenge from this machine, and Mercurial 7.2.4 run locally reports `abort: no such help topic: topics`, `hg: unknown command 'topic'`, `*** failed to import extension "topics"`. | unknown | Do not cite hg topics in the README until someone verifies its current status. |
| `gitless` | https://github.com/gitless-vcs/gitless (1,950 stars, **last push 2023-10-01**; PyPI 0.8.8 uploaded 2019-05-28) | "A simple version control system built on top of Git" - removes the staging area. | **none** | Dead, and it simplifies in the opposite direction: fewer explicit states, not more cross-session signal. |
| `myrepos` / `gita` | https://github.com/RichiH/myrepos (95 stars, **last push 2018-04-15**); https://github.com/nosarthur/gita (1,947 stars, pushed 2026-07-06) | Run commands across, or dashboard over, many repositories. | **none** | Many *repositories*, one actor. Not many sessions in one repository. |
| Optimistic concurrency control (1979) | https://en.wikipedia.org/wiki/Optimistic_concurrency_control | "OCC ... assumes that multiple transactions can frequently complete without interfering with each other. While running, transactions use data resources without acquiring locks ... Before committing, each transaction verifies that no other transaction has modified the data it has read." | **partial** | Not a tool. Included because "detect, don't lock" is 45 years old and is the formal shape of our whole design. Our contribution has to be the git-native, session-attributed, sub-file instantiation, not the philosophy. |

## Bucket 4 - Merge-conflict prediction and semantic merge

Granularity is stated per row: **FILE**, **HUNK** (line ranges), or **SYMBOL/ENTITY**, and whether the answer comes
**BEFORE** a merge (dry run) or **DURING** one.

| name | URL | what it does | granularity / timing | overlap | what it does NOT do that we do |
|---|---|---|---|---|---|
| **Grove** | https://github.com/NathanDrake2406/grove (13 stars, Rust, Apache-2.0, created 2026-02-20, pushed 2026-07-17) | "Cross-worktree conflict intelligence for git. Detects file, hunk, symbol, dependency, and schema overlaps between parallel workstreams before merge time." Own table: File = same file (Yellow); **Hunk = "Edits land in overlapping line ranges" (Red, adjacent = Yellow)**; Symbol = same function/type/export; Dependency = export/import break; Schema = migrations/deps/env/routes. Daemon + TUI + `grove check` (exit 1) + `--json` + a GitHub Action that posts a PR-vs-PR conflict matrix + a Claude Code `PostToolUse` hook running `grove check` after every Edit/Write/MultiEdit. | **HUNK + SYMBOL, BEFORE** | **high - the closest thing to our collision engine** | Its unit is the **worktree/branch**, not the session. I read the source: `crates/grove-daemon/src/git.rs` has `worktree_status()`, "Detect files that differ between HEAD and the working tree (staged + unstaged). Uses `git status --porcelain=v1 -z`" - so it **does** fold in uncommitted work, but only as a per-worktree file set. It cannot tell N sessions inside ONE shared dirty tree apart, has no session attribution, no grounded functionality brief, no dirty-tree-to-per-feature-branch splitting, and it is a Rust daemon + SQLite + npm/brew install. |
| `git merge-tree --write-tree` | https://git-scm.com/docs/git-merge-tree ; git 2.38 release notes: "'git merge-tree' learned a new mode where it takes two commits and computes a tree that would result in the merge commit" | "Performs a merge, but does not make any new commits and does not read from or write to either the working tree or index." Machine output is the tree oid plus `<mode> <oid> <stage> <path>` tuples; the human messages are documented as "**non-stable strings that should not be parsed by scripts**". | **FILE, BEFORE** | **high (it is the primitive under any such feature, ours included)** | File-level only - no line ranges when the merge auto-resolves cleanly. Cannot see a dirty working tree by design. Needs committed trees. Needs git >= 2.38 (this machine has 2.25.1 and rejects `--write-tree`). No sessions, no attribution, no brief, no splitting. |
| `git merge --no-commit --no-ff` | https://git-scm.com/docs/git-merge | A real merge that stops before committing. | **FILE, DURING** | **none as a predictor** | It mutates the index and working tree. Verified locally: exit 1, `UU` entries, conflict markers written into the file. Git's own docs warn `--abort` "may leave you in a state that is hard to back out of" when there were uncommitted changes - i.e. it is actively dangerous in a shared dirty tree. |
| `git merge-file` / `git diff --check` / `git diff -U0` | https://git-scm.com/docs/git-merge-file | `merge-file`: "Given three files <current>, <base> and <other> ... A conflict occurs if both <current> and <other> have changes in a common segment of lines." `diff --check` flags whitespace and leftover conflict markers. | **HUNK-able primitives, n/a** | **partial (these are our building blocks)** | Not a product: no pairing, no session model, no persistence, no reporting. Hunk-range intersection over `git diff -U0` output is roughly twenty lines of stdlib - **git ships the primitive, not the feature**, which is precisely why "we do hunk detection" alone is not a defensible claim. |
| git-branchless speculative merges | https://github.com/arxanas/git-branchless/wiki/Concepts (4,133 stars, pushed 2026-10-01) | "can 'speculatively' apply the operations in-memory first, without touching the working copy, and quickly abort if it turns out that they would require merge conflict resolution"; `git sync` rebases only the stacks that would not conflict. | **FILE, BEFORE** | **partial-high** | Committed commits, single actor, no sessions, no dirty tree, no line ranges. |
| GitHub mergeability | https://docs.github.com/en/rest/pulls/pulls | "When you get, create, or edit [a PR], GitHub creates a merge commit to test whether the pull request can be automatically merged ... You can review the status of the test commit using the `mergeable` key." Values `true`/`false`/`null`, plus `mergeable_state` (e.g. `clean`, `dirty`). | **FILE, BEFORE (server-side)** | **partial** | Needs a push and a PR; asynchronous (`null` while computing); a boolean per PR, not a line map; blind to anything unpushed, therefore blind to our entire scenario. |
| **weave** | https://github.com/Ataraxy-Labs/weave (1,319 stars, Rust, pushed 2026-10-10) | "Entity-level git merge driver. Resolves false conflicts git invents when independent agents edit the same file" - parses code into functions, classes and keys with tree-sitter and merges entities instead of lines. `weave preview feature-branch` = "Dry-run a merge to see what weave would do", reporting e.g. "✗ function `process`: both modified". `weave explain <file>` gives per-hunk detail read off the real git stages; `weave check` verifies the working tree against the three merge stages; ships an MCP server; also usable as a `jj` merge tool. | **SYMBOL/ENTITY, BEFORE (preview) and DURING (driver)** | **high** | Pairwise, on committed refs, one actor. No sessions, no cross-harness awareness, no dirty-tree attribution, no per-feature-branch splitting. Its preview is finer than our hunks, so do not claim "finer than git" as a differentiator. |
| sem | https://github.com/Ataraxy-Labs/sem (3,407 stars, Rust, pushed 2026-10-11) | "Semantic version control => entity-level diffs, blame, and impact analysis on top of git. 28 languages via tree-sitter." | **SYMBOL, n/a** | **partial** | Single-actor semantic VCS layer. Reusable primitives for us; no multi-session awareness. |
| Mergiraf | https://codeberg.org/mergiraf/mergiraf (458 stars on Codeberg, GPLv3, Rust, last commit 2026-10-09; GitHub mirror `qundao/mirror-mergiraf` 63 stars) | "A syntax-aware git merge driver for a growing collection of programming languages and file formats." | **SYMBOL/AST, DURING** | **partial** | A merge driver: it runs while a merge is happening to reduce false conflicts. It does not warn anyone beforehand, does not know about sessions, does not read a dirty tree. Note: `rgwood/mergiraf` 404s - cite Codeberg. |
| Spork | https://github.com/ASSERT-KTH/spork (71 stars, Java, **last push 2025-02-25**) | "AST-based structured merge tool for Java, fully Git compatible" (TSE 2022, doi 10.1109/TSE.2022.3143766). | **AST, DURING** | **none** | Academic, Java-only, merge-time, dormant. Cite as literature, not as a competitor. |
| git rerere | https://git-scm.com/docs/git-rerere | "assists the developer ... by recording conflicted automerge results and corresponding hand resolve results on the initial manual merge, and applying previously recorded hand resolutions to their corresponding automerge results." | **FILE, AFTER** | **none** | Replays past resolutions. Not prediction. |
| agent-semaphore `asem radar` | https://github.com/alwh1te/agent-semaphore (0 stars, Python, pushed 2026-08-18) | "merge-tree conflict radar ... conflict prediction before anything is committed": snapshots a dirty worktree through a temporary index and compares with `git merge-tree --write-tree`; warns at write time via a `PreToolUse` hook; "Local-first, no daemon"; state is "a single SQLite file in the git common dir". | **FILE, BEFORE** | **high** | Proves the dirty-tree + merge-tree trick is already taken. But file-level verdicts, opt-in claims, worktree as the unit, no hunk line ranges, no splitting. |
| difftastic | https://github.com/Wilfred/difftastic (25,999 stars, pushed 2026-10-12) | "a structural diff that understands syntax". | **SYMBOL, display only** | **none** | A diff **display** tool. It shows you a structural diff of what you already have; it predicts nothing and sees nobody else. Listed because reviewers confuse it with semantic merge. |
| delta / diffnav / ydiff | https://github.com/dandavison/delta (32,482 stars, 2026-10-10); https://github.com/dlvhdr/diffnav (1,590 stars, 2026-10-07); https://github.com/ymattw/ydiff (936 stars, 2026-09-30) | Syntax-highlighting pager; delta-with-a-file-tree pager; coloured incremental diff viewer. | **display only** | **none** | Same category error as difftastic. Useful complements, not competitors. |
| Yjs awareness | https://github.com/yjs/yjs (22,921 stars, pushed 2026-10-07); https://docs.yjs.dev/api/about-awareness | "The awareness protocol implements a simple network agnostic CRDT that manages user status (who is online?) and propagate awareness info". | **n/a** | **none (conceptual prior art)** | This is where "see who else is editing right now" actually comes from - collaborative editing, 2014 onwards. Our honest framing: we bring presence semantics to git's optimistic, offline, commit-based model, which is a different trade, not an invention of presence. (`ot.js` could not be located on GitHub - **UNVERIFIED**, do not cite a star count for it.) |
| Tools that do **not** exist | - | `nordmerge`, `merge-facet`, `piquant`, and a GitHub user `kerollmuss` were checked and are **absent** from GitHub, Codeberg and crates.io. | - | - | Recorded so nobody in this project cites them from an earlier draft. |

## Bucket 5 - Splitting a dirty working tree into per-feature commits/branches, and commit hygiene

| name | URL | what it does | overlap | what it does NOT do that we do |
|---|---|---|---|---|
| **GitButler** | https://github.com/gitbutlerapp/gitbutler (21,798 stars, Rust/Tauri, pushed 2026-10-11) | Docs `ai-agents/parallel-agents.mdx`: "Parallel agents do not require separate worktrees or pre-created branches"; "GitButler gives you a different option: **multiple active branches in one worktree, with each agent's commits organized onto the branch for its session**"; "You can also ask an agent to **split independent work out of the current session** ... the agent can move the relevant changes or commits to a new branch and prepare a separate PR". | **high - the single biggest threat to capability 5** | Routing is *told*, not derived: the agent decides, or a human drags. Its own docs hand overlap to the humans/agents: "If two sessions touch the same file or generated output, have the agents call out the overlap before committing", and "Parallel GitButler branches are not runtime isolation ... it can also hide accidental dependencies." No computed collision detection, no hunk prediction, no grounded brief, GUI app not a stdlib CLI. |
| git-absorb | https://github.com/tummychow/git-absorb (5,740 stars, pushed 2026-02-14) | "git commit --fixup, but automatic" - infers which existing commit each staged line belongs to and writes `fixup!` commits. | **partial** | The nearest existing **automation** of hunk-to-target assignment, but destinations are existing commits in one branch's history, not new per-feature branches; needs staged changes; one author; no sessions; no collision prediction. |
| `jj absorb` / `sl absorb` / `hg absorb` | https://github.com/jj-vcs/jj (31,971 stars); https://github.com/facebook/sapling (7,031 stars); `mercurial` 7.2.4 `hgext/absorb.py` | jj: "Move changes from a revision into the stack of mutable revisions ... moves each change to the closest mutable ancestor where the corresponding lines were modified last. If the destination revision cannot be determined unambiguously, the change will be left in [the source]". sl: "Attempt to amend each pending change to the proper commit in your stack. Absorb does not write to the working copy." hg: "use annotate information to amend modified chunks into the corresponding non-public changesets". | **partial** | Same three-way limitation: existing commits, one author's stack, no branches invented, no other sessions. Our splitter must be described as "absorb, where the destinations are new per-feature branches and the hunks came from several authors", or reviewers will call it a re-skin. |
| `git stash push -p` + `git stash branch` | https://git-scm.com/docs/git-stash | The built-in recipe: stash selected hunks, then "Creates and checks out a new branch named <branchname> starting from the commit at which the <stash> was originally created". Repeat per feature. | **partial** | Manual, N round-trips, hunk choice by hand, no grouping intelligence, no attribution, no collision awareness. **This is the baseline our splitter must beat on novelty, not merely on convenience.** |
| `git add -p` / `-i` / `-e` | https://git-scm.com/docs/git-add | `s` = "split the current hunk into smaller hunks"; `e` = "manually edit the current hunk". | **none** | The atomic primitive everything below builds on; a human answers "which hunk goes where". |
| lazygit | https://github.com/jesseduffield/lazygit (83,110 stars, pushed 2026-10-11) | TUI for git; the file-diff panel acts on individual hunks or lines, with line-by-line vs hunk selection modes and range select. | **none** | Manual staging UI. No auto-grouping, no per-feature fan-out, no cross-session view. |
| gitui / tig / magit | https://github.com/extrawurst/gitui (22,559 stars, 2026-10-06); https://github.com/jonas/tig (13,361 stars, 2026-10-08); https://github.com/magit/magit (7,240 stars, 2026-10-10) | Hunk/line staging in a terminal or in Emacs (magit dispatches staging on `region / hunk / hunks / file / files`). | **none** | Best-in-class **manual** hunk staging. Still one human, one branch, no awareness. |
| **git-splice** | https://github.com/ahnaf-lab/git-splice (0 stars, Python, created and pushed 2026-10-04) | "A git plugin (`git splice`) that slices your messy working-tree diff into a stack of minimal, independently-applicable commits using hunk-adjacency and shared-identifier analysis". README: "Requires Python 3.9+. No third-party dependencies"; "parses [git diff] into hunks, builds a graph linking hunks that are either adjacent in the same file or share a changed identifier, then greedily clusters connected hunks into independent patch sets"; "The clustering is deterministic". | **high** | This is our hunk-grouping mechanism, deterministic and stdlib-only, published eight days before this survey. It emits a commit stack on the current branch, not per-feature branches; no attribution, no collision detection, no brief. |
| **diff-split** | https://github.com/danieldelcore/diff-split (3 stars, TypeScript, created and pushed 2026-04-24) | "diff-split turns one big staged monorepo diff into multiple clean PR branches" - cherry-picks each batch onto fresh branches off the default branch, writes patch snapshots and a session branch. | **high** | This is our **output contract** (N branches + PRs) already implemented. But it "stops if unstaged changes are detected", so it cannot run on a live dirty tree; groups by package / team / N, never by hunk or intent; single actor; no sessions; no collision detection. |
| claude-split-commits | https://github.com/rayman22201/claude-split-commits (0 stars, Python, pushed 2026-03-09) | "A Claude Code skill and Python tool for splitting a dirty working tree or existing commit into multiple logical commits. Uses `git-hunk-tool`, a Python library that parses unified diffs into individually addressable hunks with metadata (function context, dependencies, fingerprints), then stages selected hunks via `git apply --cached`." | **partial** | Addressable, fingerprinted hunks already exist as a library. Commits only, one session, no branches, no awareness. |
| AI commit-splitter micro-cluster | git-agent-cli https://github.com/GitAgentHQ/git-agent-cli (81 stars, 2026-10-07); Splitify https://github.com/GH-Jaider/splitify (4 stars, 2026-06-23); ncomm https://github.com/decajoin/ncomm (1 star, PyPI 0.2.0 uploaded 2026-06-21); ai-split-commit.nvim https://github.com/cjvnjde/ai-split-commit.nvim (2 stars); plus `bililioo/split-git-commits`, `MidnightCrowing/commit-split`, `yanqr213/agentic-commit-splitter`, `johnyoonh/aicommit-split`, `cemal-nadir/auto-commit-splitter`, `kud/ai-conventional-commit-cli` | "analyzes your staged and unstaged changes, splits them into atomic commits"; "Turn messy changes into clean, atomic commits"; ncomm "reads your working tree, asks an LLM ... to split the changes into one or more Conventional Commits". | **partial** | "AI groups a messy tree into logical commits" is already a commodity, and mostly at **file** level. It is also the opposite of our design principle: an LLM decides the grouping, so it can be wrong inventively. Our deterministic, git-fact-derived grouping is the difference - say it that way, not "nobody does this". |
| git-split (TUI) / git-split (Haskell) / git-split-branch | https://github.com/Artamus/git-split (11 stars, OCaml, 2025-06-22); https://github.com/tomjaguarpaw/git-split (7 stars, Haskell, 2026-09-07); https://github.com/djpohly/git-split-branch (17 stars, **last push 2018-05-21**) | TUI commit splitting; commit splitting CLI (its README has a "Using `git-split` with agents" section); "split a Git branch into multiple branches based on arbitrary pathspecs". | **partial** | Split **existing commits**, not a live dirty tree; pathspec granularity for the branch splitter; the branch splitter is dead. |
| git-imerge | https://github.com/mhagger/git-imerge (2,848 stars, **last push 2024-07-17**) | "Perform a merge between two branches incrementally ... figure out exactly which pairs of commits conflict" and present one pairwise conflict at a time. State in `refs/imerge/NAME`. | **partial** | **Verified not a dirty-tree splitter.** Commit-pair conflict isolation between two *committed* branches; needs a clean tree. |
| StGit | https://github.com/stacked-git/stgit (680 stars, Rust, pushed 2026-10-11) | Stacked git: keep a stack of patches on top of a branch. | **partial** | Human-managed patch stack over one checkout; no sessions, no collision awareness, no automatic grouping. |
| aider | https://github.com/Aider-AI/aider (49,477 stars, pushed 2026-05-22); https://aider.chat/docs/git.html | "Aider will first commit any preexisting changes with a descriptive commit message. This keeps your edits separate from aider's edits." Attribution rule: commits aider authored get "(aider)" appended to author and committer name; "If aider simply committed changes (found in dirty files), the commit will have '(aider)' appended to the git committer name metadata." | **partial - real capability-2 prior art** | It **destroys the evidence we want to read**: pre-existing dirty files get auto-committed before it edits. That is the opposite strategy to splitting a mixed tree, and it is shipped at 49k stars. Worth naming in the README as the behaviour our tool exists to work around. |
| Claude Code checkpoints | https://github.com/anthropics/claude-code (150,234 stars, pushed 2026-10-11); https://code.claude.com/docs/en/checkpointing | Per-session file snapshots: "Claude Code keeps file snapshots for the 100 most recent checkpoints in a session", explicitly "not a replacement for version control". | **partial** | Session-scoped and blind to other sessions; only tracks files edited within the current session. |
| OpenHands | https://github.com/OpenHands/OpenHands (90,620 stars, pushed 2026-10-12) | Per-conversation git changes exposed as `GitChange{status: MOVED|ADDED|DELETED|UPDATED, path}`. | **none** | File-level, per-conversation, own runtime. |

---

## The closest five, ranked, with a blunt read of the real gap

Ranked by how much of our pitch they actually consume, not by stars.

**1. GitButler - https://github.com/gitbutlerapp/gitbutler (21,798 stars, pushed 2026-10-11)**
Consumes capability 5. Its official docs describe exactly our scenario - several coding agents, one shared working
directory, no separate worktrees, each agent's commits routed onto the branch for its session, and "split independent
work out of the current session" onto a new branch with its own PR. **What it does not do is compute anything.** Its
docs tell the humans to handle overlap themselves: "If two sessions touch the same file or generated output, have the
agents call out the overlap before committing." Our differentiation is therefore *detection and grounding*, not the
branch-splitting gesture. If our splitter is only "an agent decides which hunk goes where", GitButler already ships it
with a GUI and three years of head start.

**2. Grove - https://github.com/NathanDrake2406/grove (13 stars, Rust, pushed 2026-07-17)**
Consumes capability 3. File / **hunk ("Edits land in overlapping line ranges")** / symbol / dependency / schema overlap,
scored pairwise before merge, `--json`, exit codes, a GitHub Action, and a Claude Code `PostToolUse` hook that prints
`[conflict]` warnings into the agent's own tool output. I read its source: `worktree_status()` runs
`git status --porcelain=v1 -z --no-renames`, so it **already folds uncommitted work into the picture**. What it cannot
do is separate two sessions inside one dirty tree - its unit of identity is the worktree/branch, so five agents in one
working directory collapse into one row. **Any README sentence of the form "we detect hunk-level overlap" is now a
feature parity claim, not a novelty claim.**

**3. Foremerge - https://github.com/naw103/foremerge (538 stars, Apache-2.0, Rust, pushed 2026-10-04)**
Consumes the "deterministic, non-LLM, agent-neutral conflict detection with advisory warnings" framing, which is a
large part of our credibility story. Its store lives in `.git`, "every agent on your machine sees the same picture,
whether it is Claude, Codex, or Cursor", it "never asks a model to judge conflicts", and it "never locks a file". It
also **beats us** on semantic collisions across different files (replace `PaymentService` vs extend `PaymentService`),
which pure line-range overlap cannot see. Its limits are real and stated: cooperative announcement, isolated worktrees,
"coordination between machines is outside this project's scope".

**4. AgentColab - https://github.com/MeharPro/AgentColab (0 stars, Python 3.9+, pushed 2026-09-05)**
Consumes our engineering-aesthetic pitch: coordination carried on a git ref, "no server to run for it, no account to
make", zero dependencies, deliberately no locks, and - crucially - touched-files **derived from `git diff` against the
merge base** rather than declared. Its limit is the same wall as Grove's: per-branch, so a single shared dirty tree is
invisible to it, and file-level only. Zero stars and two months old, but the design is the same design.

**5. The shared-dirty-tree awareness cluster - Beacon (4 stars), Traffic Control (2 stars), Collide (1 star), SAGE
(4 stars), agent-semaphore (0 stars)**
Individually tiny, collectively they consume the sentence "we handle several agents in ONE working tree". Beacon
injects a pre-edit collision warning and guards `checkout`/`stash`/`add -A` in a shared tree; Traffic Control is
explicitly "a same-tree alternative to git worktrees" and injects a who-is-doing-what board at `SessionStart`;
agent-semaphore does `git merge-tree` prediction over a temporary index "before anything is committed" with state in
the git common dir; SAGE already separates "touched (git fact)" from "claimed (intent)" and prints a merge brief.
**All of them are cooperative.** That is the one wall none of them has crossed, and it is where our remaining novelty
lives.

### What is actually left, stated without inflation

| capability | status | the honest sentence |
|---|---|---|
| Observe refs/worktrees/dirty files | **taken as a mechanism** | Grove, agent-semaphore and SAGE all read git state. Our angle is *which* state (per-worktree index, shared `refs/`, reflogs) and *for whom*. |
| Attribute work to sessions | **open, and the strongest claim we have** | No tool in this survey has a session object over uncommitted work. Verified: git itself emits no session identity for dirty files. Caveat: git-ai (2,829 stars) owns *commit-time* line attribution and must be interoperated with, not reinvented. |
| File + hunk collision detection | **taken** | Grove ships hunk line-ranges; weave ships entity-level preview; grit and MAK ship symbol-level arbitration. Ours must be over **uncommitted edits inside one shared tree**, which none of them does. |
| Grounded brief (code extracts facts, LLM cannot invent them) | **partially open** | Foremerge shares the "never ask a model to judge" principle; SAGE prints a merge brief. Nobody frames grounding-as-anti-hallucination as the design property, and nobody's brief is built from per-session dirty state. |
| Dirty tree to per-feature branches | **taken as a gesture, open as an inference** | GitButler ships the workflow with human/agent routing; git-splice ships deterministic hunk clustering; diff-split ships the N-branch output but refuses unstaged changes. **Nobody infers the feature partition from the tree itself and then writes the branches.** That is the narrowest, most defensible claim left. |
| stdlib-only / no daemon / local | **not a differentiator** | AgentColab (git ref, 0 deps), dibs (one static binary), fencepost (no daemon), Watchbill (markdown + git), parallel-sessions (pure Bash, "0 servers"), SAGE (0 npm deps), agent-semaphore ("no daemon, no cloud, no account"). |

**Bottom line.** The defensible core is one sentence long and it is about *sessions* and *non-cooperation*: derive, from
git plumbing alone, which session is editing which lines of one shared dirty tree, warn before the edit and before the
merge, and split that tree into per-feature branches by inference rather than by instruction. Everything else in the
pitch is contested territory.

---

## Claims we must NOT make

Each of these is refuted by a fetched source. Writing any of them would make the README look either uninformed or
dishonest.

1. **"No existing tool gives agents cross-session awareness of a repository."** False. Roughly 40 live 2026 projects
   claim exactly this: Foremerge (538 stars), concord-mcp (456), mcp_agent_mail (2,202), Beacon, Traffic Control,
   Collide, SAGE, AgentColab, agent-semaphore, oxtail, Weaver, Hivemind, Watchbill, dibs, fencepost, standup-board,
   `wolfiesch/cmux-control` ("cross-session awareness for coding agents").
2. **"Nobody warns before the edit / before the merge."** Grove's `PostToolUse` hook, Beacon's injected pre-edit
   warning, Traffic Control's `PreToolUse` clearance, wit's "detect conflicts before code is written", Foremerge's
   pre-write advisory, agent-semaphore's "conflict prediction before anything is committed", radar's pre-merge test run.
3. **"Hunk-level or sub-file conflict detection is novel."** Grove: "Hunk | Edits land in overlapping line ranges".
   weave: entity-level preview reporting "function `process`: both modified". grit: tree-sitter function-level claims.
   sem: entity-level diffs and blame. Hivemind: per-function claims. MAK: symbol-granularity arbitration in a shared dir.
4. **"Splitting a shared working tree into per-feature branches is new."** GitButler's docs, verbatim: "multiple active
   branches in one worktree, with each agent's commits organized onto the branch for its session" and "ask an agent to
   split independent work out of the current session".
5. **"No daemon / local-only / zero-dependency / git-ref transport is our differentiator."** AgentColab, dibs,
   fencepost, Watchbill, parallel-sessions, SAGE, agent-semaphore, `hiroyuki0504/agents-kit` all already claim some
   version of this.
6. **"We invented agent attribution."** git-ai (2,829 stars) does line-level agent/model/prompt attribution via an open
   standard carried in git notes with vendor adoption. aider (49,477 stars) already tags commits from dirty files with
   "(aider)" in the committer metadata. Claude Code checkpoints are session-scoped snapshots.
7. **"Predicting a merge conflict without touching the working copy is new."** `git merge-tree --write-tree` (git >=
   2.38) "does not read from or write to either the working tree or index"; git-branchless speculative merges apply
   operations "in-memory first, without touching the working copy"; GitHub computes `mergeable` server-side.
8. **"Advisory rather than blocking is our insight."** Foremerge: "It never locks a file or blocks an agent, because a
   single crashed agent would then stall the whole fleet". AgentColab: "There is deliberately no lock." Beacon:
   "advisory ... fails open". mcp_agent_mail documents its leases as advisory.
9. **"Semantic merge is unsolved."** Mergiraf (458 stars on Codeberg, active 2026-10-09), weave (1,319), sem (3,407),
   Spork (71, academic).
10. **"Memory tools are blind to the repo, unlike us."** True but irrelevant - claude-mem (99,745), mem0 (66,997),
    Beads (27,813), Letta (25,107) are a different category. Attacking them reads as padding and invites a "so what".
11. **"Works with every harness out of the box."** Most competitors *claim* harness neutrality and are Claude Code
    first in practice (Beacon, Traffic Control, shared-tree-guards, agent-traffic-control). Do not claim broader
    harness support than we have actually tested, and say which harnesses we have tested.
12. **"git cannot tell you anything about concurrent work."** Overstated. Git shares `refs/` across worktrees, shares
    `refs/stash`, shares branch reflogs, exposes `reference-transaction` hooks from the common dir, and can predict a
    merge with `merge-tree`. Our README should say git provides the substrate and lacks the *session* concept - that is
    both true and stronger.
13. **Any star count, date, or quote not re-verified at publish time.** This space moved ~40 repos in nine months;
    re-run the survey before shipping.

---

## Honest positioning paragraph (adapt freely)

> Several tools already coordinate AI coding agents on a shared repository, and the space grew quickly through 2026:
> GitButler runs multiple agents over one working directory with per-session branch routing, Grove scores hunk- and
> symbol-level overlap between worktrees before a merge, Foremerge detects intent conflicts deterministically across
> Claude Code, Codex and Cursor, and a long tail of lease, claim and presence layers covers agents that share a single
> dirty tree. What all of them share is that awareness is **cooperative**: the other session has to install something
> and declare itself, and an agent that never opted in is invisible. This tool takes the opposite bet - it derives
> everything from git plumbing (`worktree list --porcelain`, per-worktree indexes, shared `refs/`, `diff -U0`), so it
> describes sessions that never heard of it, including the pre-existing dirty files that a harness like aider will
> happily commit out from under another agent. Its remaining claims are deliberately narrow: session attribution of
> *uncommitted* work, hunk-range overlap between edits that have never been committed, and splitting one mixed dirty
> tree into per-feature branches by inference rather than by instruction. It does not do semantic merge (use Mergiraf,
> weave or `sem`), it does not do long-term agent memory (use claude-mem, mem0 or Beads), it does not do line-level AI
> provenance (adopt git-ai's notes standard), and it is not a lock manager - it is optimistic concurrency control
> applied to a git working tree, which is a 1979 idea, not ours.

---

## Method, and what is unverified

**Method.** GitHub search + repo API with a `gh auth token` (5,000 requests/hour), PyPI JSON API, Codeberg, primary
docs and man pages, and raw source files. Four research workers ran buckets 1, 2, 4 and 5 in parallel against the same
helper (`/home/rk/Projects/priorart.py`, cache in `/home/rk/Projects/.priorart_cache/` so every fetch is auditable);
bucket 3 and the cross-checks were done directly. Every number in this file was re-fetched by the author, not copied
from a worker. Local git experiments ran on this machine's git 2.25.1.

**Search-method caveat, stated plainly.** GitHub repository search matches keywords in name/description/README. A query
returning `total_count: 0` is weak evidence of absence, not proof. Where this file says a capability "appears open"
(dirty-tree-to-per-feature-branch inference; awareness without any agent-side install), that rests on ~15 distinct
query phrasings plus manual reading of the ~40 hits, not on a single zero-result query.

**Unverified - do not publish these as claims:**

- **Conductor (conductor.build)** - closed source, no GitHub org; only third-party "alternative to Conductor" repos found.
- **Mercurial topics** - mercurial-scm.org and heptapod serve an Anubis anti-bot challenge from this machine; Mercurial
  7.2.4 run locally reports no `topics` help topic, no `topic` command, no importable `topics` extension.
- **Perforce / ClearCase exclusive checkout** - `docs.perforce.com` would not connect, the manuals URL 404s, and the
  Wikipedia ClearCase text fetched here had no usable checkout/lock passage. The lock-vs-optimistic framing is grounded
  only in the `git lfs lock` man page and the OCC article.
- **`ot.js`** - could not locate the canonical repository on GitHub; cite Yjs (22,921 stars) for awareness-protocol
  prior art instead.
- **Closed products**: Cursor background agents, GitHub Copilot coding agent, Devin, Terragon, Amp, Jules, OpenHands
  cloud, `codeset/codeset-agents`, `21st-dev`/`punkpeye` `mcp-github` (both 404; the official git MCP server is
  `src/git` inside `modelcontextprotocol/servers`), Backboard, Sourcegraph AI attribution as a shipped tool.
- **Star counts for the smaller entries in the bucket-2 micro-cluster row** (fencepost, Watchbill, shared-tree-guards,
  Weaver, oxtail, standup-board, agents-kit, pact) - their existence and behaviour come from a worker's `repo()` fetch
  recorded in `priorart_bucket2.md`; the author did not re-fetch each, so no numbers are quoted here.
- **Everything in this file is a 2026-10-12 snapshot.** Re-verify before publishing.
