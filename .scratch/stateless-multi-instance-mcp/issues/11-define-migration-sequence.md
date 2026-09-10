# Define the migration sequence and rollback checkpoints

Type: grilling
Status: open
Blocked by: 12, 13, 14, 15, 16, 17, 18, 20

## Question

In what order should the current single-instance, session-oriented implementation be replaced by the specified adapter, Target Runtime, explicit-target catalog, operation machinery, packaging, diagnostics, and compatibility behavior so every intermediate checkpoint is testable, avoids two competing execution paths, and has a clear rollback boundary before the signed release is accepted?

Also define the minimum first release: which tools, transports, and packaging form it ships with, and which requirements of **Define the conformance and acceptance contract** apply at each checkpoint versus only at the signed release. Without that, the first checkpoint inherits the full acceptance matrix and is unreachable. Apply the explicit unsigned developer-build policy already settled in [Decide product ownership, signing identity, and upstream relationship](18-decide-ownership-and-signing.md#answer). Identify where upstream agreement and signing readiness gate production, using [Establish upstream release ownership and signing arrangements](21-establish-upstream-release-arrangements.md); sequencing and unsigned development need not wait for those arrangements.

Apply the development-versus-release baseline policy in [Choose the pyRevit engine for host-side runtime code](16-choose-host-engine.md#answer). Identify the checkpoint that records the concrete release-time pyRevit minimum and gathers acceptance evidence on that stock baseline.

Name the checkpoint and verification evidence for removing the old tool-specific Routes scaffolding under [Retire the temporary legacy execution path from the target-identity decision](14-retire-legacy-execution-path.md). Its removal deadline is fixed before the first accepted signed release; intermediate reuse must satisfy that decision's Target Runtime boundary and cannot restore a client-facing targetless path.
