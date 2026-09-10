# Commit the map and merge research evidence to master

Type: task
Status: claimed
Assignee: NateZwainleskPLA
Blocked by: none

## Question

Bring the wayfinder map and its evidence under version control so a pruned worktree or lost `.scratch` directory cannot erase the route.

Today the map, every ticket, `CONTEXT.md`, and `docs/research/` are untracked on `master`. The evidence for **Research the released stateless MCP contract and SDK surface** and **Research packaging an on-demand MCP helper within a pyRevit extension** exists only on two `research/*` branches checked out in worktrees outside the repository, and both tickets link to those worktree paths.

Do: merge or cherry-pick the two research documents into `docs/research/` on `master`; repoint the two ticket answers at the in-repo paths; decide whether `.scratch/` stays the map's home or moves under `docs/`; commit the map, tickets, `CONTEXT.md`, and research docs; prune the research worktrees once their content is on `master`. Record the resulting paths in the answer.

## Comments

### Preservation completed; residual checkout cleanup blocked — 2026-09-10

- Kept the canonical map at [Specify a stateless, multi-instance Revit MCP architecture](../map.md), with child tickets in this directory. Its Notes now document the local Markdown tracker convention.
- Cherry-picked the original research commits with provenance onto `master`: `ea053a6` adds [MCP 2026-07-28 migration baseline](../../../docs/research/mcp-2026-07-28-migration-baseline.md); `58d7585` adds [Packaging an on-demand MCP helper inside a pyRevit extension](../../../docs/research/pyrevit-mcp-helper-packaging.md). Both files match their source commits unchanged. The research ticket answers now use these repository-relative paths.
- Commit `5f64a30` preserves the map, all 21 tickets, the catalog proposal pointer, [domain context](../../../CONTEXT.md), and the two later research notes in `docs/research/`. Checked 71 local Markdown links across 28 files and passed the staged whitespace check. No migration implementation changed. Commits remain local; nothing was pushed.
- Both research worktrees were clean, including ignored files, before cleanup. Git removed the helper-packaging worktree. Git partially removed the MCP-contract checkout because of read-only directory attributes; its orphaned administrative registration was subsequently pruned through Git. Only the main checkout and the execution-lane prototype remain registered. Both research branch refs are retained.
- Remaining cleanup: the redundant directory `D:/OneDrive - PLA Designs/Documents/Dev/pyRevit MCP/Dev/pyrevit-mcp-research-mcp-2026-07-28-contract` still contains 48 files, each verified against its original blob in `0ad8fdf86571b5639018870e25589bfdc4482795`. Automatic approval review rejected both manual recursive cleanup and a narrower command deleting only verified files and empty directories, with the sole stated reason `blocked by policy`. No further deletion attempted.
- Leave this ticket claimed until the residual directory is removed. Then record the resolution and add its pointer to the map. The prototype branch and worktree remain available to [Choose the host listener lifecycle after the Routes reload failure](20-choose-host-listener-lifecycle.md).

### Cleanup authorized; execution still blocked — 2026-09-10

The user explicitly approved cleanup: "cleanup is fine." Retried the narrowly named residual-directory deletion with absolute-path validation and committed-blob checks. Automatic approval review rejected the command before execution, again reporting only `blocked by policy`. The directory remains; user permission is no longer an outstanding prerequisite. No resolution or map decision pointer was recorded because cleanup has not completed.
