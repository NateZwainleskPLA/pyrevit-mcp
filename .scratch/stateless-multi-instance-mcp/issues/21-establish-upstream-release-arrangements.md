# Establish upstream release ownership and signing arrangements

Type: task
Status: open
Blocked by: 18

## Question

Obtain upstream maintainer agreement to the release model chosen in [Decide product ownership, signing identity, and upstream relationship](18-decide-ownership-and-signing.md#answer), so the migration specification can name a feasible owner and release path rather than assume upstream will provide one.

This is a human-in-the-loop coordination task. Prepare a concrete proposal for the human to take to upstream; sending messages requires explicit authorization. Resolve only with an actual response or other attributable upstream agreement, not the agent's prediction of acceptance.

Record evidence and the resulting arrangements:

- Whether upstream accepts maintenance and production release responsibility for this contribution, without requiring Nate to become the maintainer.
- The intended signing publisher and the upstream-controlled role or service that holds the private key or authorizes signing. Record references and responsibilities, never secret material.
- Where release builds run, who approves them, and how the bundled signed helper enters the versioned extension package and distribution channel. Establish whether upstream accepts the proposed artifact packaging; do not assume binaries must be committed to source control.
- Whether suitable signing infrastructure already exists; if not, who will arrange it during implementation and what prerequisites remain before a signed release.

If upstream declines or requires a different packaging or ownership model, record that response and surface the precise decision needed to reconcile the installation and acceptance contracts. Do not silently select a personal publisher, waive production signing, or start an independent fork distribution.

This task unblocks final specification of the upstream release path. Unsigned development and migration-sequence planning may proceed meanwhile, with production explicitly gated on these arrangements and their later implementation. Credential purchase/provisioning, release-pipeline implementation, and publishing are implementation work outside this planning ticket.
