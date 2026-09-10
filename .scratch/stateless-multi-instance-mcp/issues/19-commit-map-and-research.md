# Commit the map and merge research evidence to master

Type: task
Status: claimed
Assignee: NateZwainleskPLA
Blocked by: none

## Question

Bring the wayfinder map and its evidence under version control so a pruned worktree or lost `.scratch` directory cannot erase the route.

Today the map, every ticket, `CONTEXT.md`, and `docs/research/` are untracked on `master`. The evidence for **Research the released stateless MCP contract and SDK surface** and **Research packaging an on-demand MCP helper within a pyRevit extension** exists only on two `research/*` branches checked out in worktrees outside the repository, and both tickets link to those worktree paths.

Do: merge or cherry-pick the two research documents into `docs/research/` on `master`; repoint the two ticket answers at the in-repo paths; decide whether `.scratch/` stays the map's home or moves under `docs/`; commit the map, tickets, `CONTEXT.md`, and research docs; prune the research worktrees once their content is on `master`. Record the resulting paths in the answer.
