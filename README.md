# muster

**Cross-session awareness for AI coding agents working on the same repository.**

Five agent sessions are talking to your repo right now. None of them know about
each other.

`muster` observes the repository - branches, worktrees, and the dirty working
tree - groups the uncommitted mess into lanes, tells each agent what the other
lanes are building, warns before two of them edit the same lines, and integrates
the results in isolation.

It works without any agent cooperating. Nothing has to declare anything for the
picture to exist.

```
$ muster brief --repo ~/Projects/videoEditor
muster brief  /home/rk/Projects/videoEditor
base origin/main · you on feature/conversational-topic-editor · observed 2026-10-12T10:44:12+0000 · git 2.25.1

YOU
  session prime-agent/6a52d4daec30
  not declared - run `muster claim --intent "..." --paths a,b` so other sessions can see you

UNCOMMITTED WORK IN THIS WORKING TREE - 4 lane(s), attribution inferred
  - brag-2026-10-08-110237              90 file(s)  high     4d ago
      .brag_run_root.json(+1), brag-2026-10-08-110237/work/landing.png, brag-2026-10-08-110237/work/topics.png  +87 more
      why: everything under brag-2026-10-08-110237/ is new, so it arrived as one piece of work
  - claim-audit                         14 file(s)  medium   30h ago
      video_editor/.../marketing/testimonials.jsx(-47), reports/claim-audit.md(+40), video_editor/.../omponents/marketing/faq.jsx(+55)  +11 more
      why: touched together within 74m across reports, video_editor, video_editor/src/app
  - ad-simulation-data                   8 file(s)  medium   2d ago
      reports/ad-simulation-report.md(+105), reports/ad_simulation_data/sweep_run1.jsonl(+11), reports/.../ion_data/sweep_run2_repeat.jsonl(+5)  +5 more
      why: touched together within 1m across reports, reports/ad_simulation_data
  - demo-submit                          4 file(s)  medium   4d ago
      video_editor/public/demo-intake.html(+49), app.py(+39), video_editor/.../pp/api/demo-submit/route.js(+66)  +1 more
      why: touched together within 52m across ., video_editor, video_editor/public

OTHER BRANCHES - 1 with work not in origin/main
  - feature/conversational-topic-editor  25 ahead / 0 behind  [29h ago]
      feat(llm): labels, fallback analyzer and frame captions use ; feat(chat): real multi-turn chat via llm_client, reasoning_d
      203 files touched: .dockerignore, .env.example, .github/workflows/tests.yml

COLLISIONS - none found between your working tree and other lanes

WATCH OUT
  - 1 uncommitted file(s) over 400 added lines - commit or split them: reports/.../ad_comments_by_variant.md

NEXT
  muster settle            # split this working tree into reviewable lanes
  muster plan feature/conversational-topic-editor   # what integrating it would do
  muster claim --intent "..." --paths a,b   # tell other sessions you are here
```

## The problem

A repo now gets worked on by Claude Code in one terminal, opencode in another, a
Codex run in the background, a scheduled job overnight, and you in an editor.
They share one `.git`. Git is a good substrate - it already replicates refs across worktrees and predicts merges - but it has no concept of a *session*, so:

- **Nobody knows what anybody is doing.** `git status` shows 40 dirty files with
  no hint about which lane each belongs to.
- **Agents destroy each other's work.** `git checkout .`, `git reset --hard`,
  `git clean -fd`, `git stash` are routine agent commands. In a shared tree they
  delete another session's uncommitted work.
- **Duplicate and conflicting work.** Two sessions build the same endpoint in
  different branches and find out at merge time, hours later.
- **Integration is left to whoever notices.** Branches drift 25 commits from the
  base because no one is watching.

This is not hypothetical. The repo used to validate this tool had five unrelated
work streams sitting uncommitted in one working tree at the same time, and a
branch 25 commits from `main`. See [validation](docs/VALIDATION.md).

## Install

```bash
uv tool install git+https://github.com/rkyla/muster.git
# or: pipx install git+https://github.com/rkyla/muster.git
```

Not published to PyPI yet. The dist name `muster-cli` is free there as of 2026-10-12; `muster` itself is taken by an unrelated package.

No runtime dependencies, and no build step beyond packaging - it shells out to
`git`, which you already have. Python >= 3.9.

Then, in the repo the agents share:

```bash
cd your-repo
muster init            # writes .muster/, adds the rules to AGENTS.md
```

`muster init` appends a delimited block to `AGENTS.md` (and `CLAUDE.md` if you ask)
that tells agents the four commands to use and the hard rules for a shared tree.
Most coding agents read `AGENTS.md`, so the instructions arrive without any hook.

## How agents use it

| Command | When | What it answers |
|---|---|---|
| `muster brief` | session start | What is everyone else building, and what collides with me? |
| `muster claim --intent "..." --paths src/api,tests` | before editing | I am here, this is my scope |
| `muster touch src/api/users.py` | before each file | safe / FYI / caution / stop |
| `muster done --summary "added /demo-leads"` | session end | I am finished, this is what landed |
| `muster map` | debugging | the full collision matrix |
| `muster features` | reviewing | what functionality each branch actually carries |
| `muster plan feature/x` | integrating | what merging it would do, including conflicts |
| `muster merge feature/x --apply` | integrating | do it in an isolated worktree, verified |
| `muster settle --apply` | cleanup | split a mixed working tree into reviewable lanes |
| `muster watch` | orchestrator | tell me when another lane moves |

Every command has `--json`. `muster touch` exits non-zero on `caution` and
`stop`, so it works as a gate in a script or hook. It deliberately does **not**
fail on your own unattributed work: a gate that cries wolf is a gate agents learn
to ignore.

The rest of the surface is the ledger behind those answers:

| Command | What it does |
|---|---|
| `muster scan` | observe once, write the ledger, print nothing much (what the hook runs) |
| `muster whoami` | the session id muster derived from this harness, and why |
| `muster events` | the append-only log: claims, sessions, merges, settles |
| `muster forget` | drop this repo's ledger from `~/.local/state/muster` |

## What it observes

Nothing depends on agents cooperating. `muster claim` makes the picture better;
it is not required for the picture to exist.

| Source | What it yields |
|---|---|
| `for-each-ref`, `merge-base`, `rev-list` | every branch and remote, ahead/behind the base, commits and files each adds |
| `worktree list`, `status --porcelain -z` | every worktree and every uncommitted path |
| file mtimes | edit-time clustering: files touched in the same window in the same area are probably one task |
| added markdown headings | what a branch says it does, in its own words |
| declared claims | intent and scope, attributed to a harness and session id |
| `reflog`, stashes | abandoned and hidden work |

Session identity comes from the harness environment (`CLAUDE_CODE_SESSION_ID`,
`CODEX_THREAD_ID`, `RLM_SESSION_ID`, `CURSOR_TRACE_ID`, and others). When a harness
exposes no id, identity falls back to the process tree and is labelled `inferred`.
Run `muster doctor` to see what is visible.

## Collision detection is line-level, and over uncommitted edits

"Both branches touch `app.py`" is noise. `muster` compares the actual line ranges
each side edits, taken from `git diff --unified=0`:

```
same-hunk    overlapping lines in the same region      -> STOP
overlapping  nearby ranges, within a few lines         -> CAUTION
same-file    same file, clearly separate regions       -> FYI
```

For git >= 2.38 conflict prediction uses `git merge-tree --write-tree`. On older
git it falls back to a real `git merge --no-commit` inside a throwaway worktree,
which is slower but exact. `muster doctor` reports which path is in use.

Hunk-level overlap is not new - Grove and agent-semaphore do it. The difference is
the input: `muster` compares edits that have never been committed, from sessions
that share one working tree, where there is no branch to diff against.

## The orchestrator

`muster merge` and `muster settle` are the only commands that write, and they are
conservative by design:

- **Your working tree is never touched.** Merges and splits happen in a temporary
  `git worktree` outside the repo.
- **Dry-run is the default.** `--apply` is required to write anything.
- **A merge commits only if your `verify` command passes** (`.muster/config.toml`,
  e.g. `verify = "python -m pytest -q"`). If it fails, the merge is aborted.
- **If the target branch is checked out**, the result lands on a new `muster/*`
  branch instead of moving a branch out from under a running session.
- **`settle` never deletes anything.** It copies each cluster of dirty files onto
  its own branch, based on the commit your working tree is sitting on - which is
  what the uncommitted work is relative to. Your working tree is exactly as it
  was, file for file.
- **Muster signs its own commits** as `muster <muster@localhost>`, so a merge or
  a settle still works on a fresh container with no git identity configured.
  Override with `MUSTER_COMMITTER_NAME` / `MUSTER_COMMITTER_EMAIL`. Your own
  commits are never touched.

`muster watch` is the long-lived observer: it re-scans on an interval and emits
`ref-new`, `ref-moved`, `file-dirtied`, `file-cleaned`, and `collision-new`
events, optionally calling a `notify` command.

## Sharing state across machines

`.muster/` is local. For sessions in different clones or on different machines,
`muster sync push` publishes the ledger to `refs/muster/ledger` - one JSON blob on
a git ref, invisible in working trees and pull requests. `muster sync pull` merges
it in, newest write per session wins, and refuses a ledger whose `repo_id` does
not match. `repo_id` is the repository's root commit, so clones of one project
agree while two unrelated repositories that happen to share a remote stay apart.
Git already replicates refs, so there is no server to run.

Only declared state is published: session ids, intents, path scopes, events. No
file contents and no commit bodies leave the machine.

## Limits, honestly

- **Attribution of uncommitted work is inference, not fact.** Clusters come from
  directory affinity and edit times. `muster` labels every inferred lane
  `inferred` and gives the clustering reason, but it cannot know which agent wrote
  a file unless that agent declared it.
- **It cannot prevent a determined agent.** Claims are advisory. `muster touch` is
  a gate only if something calls it. The `AGENTS.md` block and the session hook are
  how you make agents call it.
- **It is not a merge tool.** Conflicts are predicted and listed, not resolved.
  Semantic merge tools like mergiraf do the resolving; `muster` tells you a
  conflict is coming before you spend an hour on it.
- **Same-machine focus.** Cross-machine sync exists but is a ledger hand-off, not
  live coordination.
- **Git >= 2.20 required** (worktrees, `status -z`). Developed and tested against git 2.25.1; the `merge-tree --write-tree` path (git >= 2.38) is unit-tested but has not been run against a 2.38+ binary here.

## How this differs from what already exists

This space is not empty. A survey of 73 repositories (see
[docs/PRIOR_ART.md](docs/PRIOR_ART.md), star counts re-verified against the GitHub
API on 2026-10-12) found roughly 40 live projects that claim to stop AI agents
clobbering each other. The four that matter:

| | what it already does | what it does not do |
|---|---|---|
| [GitButler](https://github.com/gitbutlerapp/gitbutler) (21.8k) | several agents over one working directory, commits routed onto a branch per session, "split independent work out of the current session" | it computes nothing about overlap; its docs tell the humans to have the agents call the overlap out themselves |
| [Grove](https://github.com/NathanDrake2406/grove) | file, **hunk**, symbol, dependency and schema overlap scored before merge, `--json`, a Claude Code hook | its unit of identity is the worktree, so five sessions in one dirty tree collapse into one row |
| [Foremerge](https://github.com/naw103/foremerge) (538) | deterministic, non-LLM intent-conflict detection across Claude/Codex/Cursor in a `.git` store; beats us on cross-file semantic collisions | cooperative: agents must announce; isolated worktrees; cross-machine out of scope |
| [AgentColab](https://github.com/MeharPro/AgentColab) | coordination carried on a git ref, zero deps, no server, touched files derived from `git diff` | per-branch and file-level, so a single shared dirty tree is invisible to it |

The shared-dirty-tree cluster (Beacon, Traffic Control, Collide, SAGE,
agent-semaphore) already covers "several agents in one working tree". Every one of
them is **cooperative**: they work because agents announce what they are doing.

What is left, stated without inflation:

1. **Sessions over uncommitted state.** No tool surveyed has a session object for
   work that has never been committed. Git itself emits no session identity for a
   dirty file - `git status --porcelain=v2` says nothing, blame says
   `Not Committed Yet`. `muster` builds that object, from the harness environment
   when it can and by inference when it cannot, and labels which it did.
2. **Awareness without cooperation.** The observation path reads only git. An
   agent that has never heard of `muster` still shows up as a lane, because its
   files are dirty and its branch exists.
3. **A grounded feature summary.** Each claim in `muster features` traces to a
   commit subject, a changed path, or a line the branch itself added to a
   document. If a model is used for prose, a guard drops any sentence containing a
   number, path, or sha that git did not report.

`git-ai` (2.8k) owns commit-time line attribution via git notes and is the right
thing to interoperate with; `muster` does not reinvent it. If your team can adopt
GitButler or Grove, evaluate those first - they have GUIs, communities, and years
of head start. `muster` is for the case they leave on the table: agents that will
not cooperate, in a tree that is already dirty.

## Development

```bash
uv venv && uv pip install -e . pytest
pytest                                  # synthetic 5-lane repo fixture
python validation/run_validation.py     # read-only checks against a real repo
python validation/run_validation.py --writer   # + settle --apply against a copy
```

## License

MIT
