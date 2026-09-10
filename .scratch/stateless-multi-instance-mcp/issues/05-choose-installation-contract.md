# Choose the installation and runtime packaging contract

Type: grilling
Status: resolved
Blocked by: 02, 04

## Question

Given the viable packaging mechanisms and chosen runtime topology, what installation, first-run, Codex-connection, update, and troubleshooting experience must the specification require, and when is exposing a user-managed runtime prerequisite justified despite the preference to avoid it?

## Answer

### Production packaging and compatibility

- Production requires a signed, self-contained Windows-x64 MCP Adapter bundled within the Extension Footprint. Installing or starting the product requires no user-managed Python or `uv`, elevation, internet access, first-run download, or separate background installation. The packaged helper is validated for signature, integrity, architecture, and compatibility before launch. A helper failure must not prevent the extension's internal pyRevit Routes or status controls from loading.
- The pyRevit extension and MCP Adapter have independent product versions because they will change at different rates. A compatibility-breaking Target Runtime interface change coordinates their major versions for human understanding, while an explicit interface-revision handshake enforces compatibility at runtime. The adapter declares its supported revision range, refuses to route to an incompatible exposed host, and reports the incompatibility explicitly rather than hiding it or attempting execution.
- A user-managed Python or `uv` path is an opt-in developer/support escape hatch only. Production never silently downloads dependencies, changes runtimes, or falls back to it. If the preferred packaged-helper mechanism cannot meet production acceptance criteria, another self-contained mechanism such as embeddable CPython may replace it without weakening the no-prerequisite contract.

### Installation, startup, and target exposure

- Use one distribution channel and no in-product updater initially. Every versioned pyRevit extension package declares and carries one pinned compatible adapter artifact. Either version may remain unchanged across package releases; an adapter-only change is distributed as a new extension package even if its pyRevit code is otherwise unchanged. Update and rollback mean installing the desired package while Revit is closed, not independently mutating a live helper.
- Loading the extension creates a **Revit Host**, registers its internal pyRevit Routes, and cooperatively starts or reuses the per-user MCP Adapter even when no host is exposed. The adapter may therefore remain reachable and truthfully report that it has no Revit Targets. Its normal host-cooperative lifetime ends after no Revit Hosts remain for the topology's grace period, not merely because no targets are exposed. Explicit client startup before any host exists follows [Decide the fate of the Revit launch and installation-discovery tools](12-decide-launch-tools-fate.md), which also owns the independent, default-off launch permission and startup-window setting. Provide these settings in local configuration and the Revit MCP Status surface, with documented startup instructions usable while Revit is closed.
- The consent boundary is between each Revit Host and the adapter. On a new installation, the per-user default is **do not expose**. A host becomes a **Revit Target** only when exposure is enabled; disabling exposure removes it from discovery and new admission immediately, drains any running operation while preserving inspection and cancellation, then expires that target generation. Re-enabling creates a new generation. Multiple simultaneous hosts can be enabled or disabled independently.
- The persisted per-user exposure default applies only to future hosts. Each running host may override it for its own lifetime without changing other running hosts. Changing “Automatically expose Revit” changes the default for subsequently started hosts and does not retroactively expose or hide existing ones.
- Discovery may reveal only a privacy-preserving availability summary for disabled hosts: host count, unexposed count, and the action needed to expose one. It exposes no disabled-host identity, Revit metadata, document title, path, or Document Target. This is sufficient for an agent to tell the user why the Target Snapshot is empty.

### Client-owned connection

- The product is agent-client agnostic. It never discovers, edits, or owns Codex or another client's configuration; connection setup is initiated and owned from the client side. Codex currently accepts a Streamable HTTP endpoint through `mcp_servers.<id>.url` in its user configuration, but that client detail is guidance rather than part of this product's installation workflow ([official OpenAI configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference#configtoml)).
- Publish one non-secret, atomically replaced, current-user **Connection Descriptor** at the fixed location owned by [Reconcile the per-user storage root across topology, installation, and Forensic Record decisions](13-reconcile-storage-root.md), alongside product settings and evidence under one Local AppData root. It advertises the stable loopback endpoint, adapter version, protocol/interface revision, and advisory health state. It contains no targets or documents, grants no access, and is never authoritative: a client must still connect and verify adapter identity, compatibility, and health.
- Use one stable default loopback URL with an advanced per-user port override. A change takes effect after adapter restart and updates the descriptor. If the configured port is occupied, accept it only when an identity and compatibility health check proves it is this adapter; otherwise report a collision and remain stopped rather than choosing a random port.

### Troubleshooting and cleanup

- Provide one **Revit MCP Status** surface in every Revit Host. It shows and controls that host's exposure, the persisted future-host default, extension and adapter versions, interface compatibility, configured endpoint, adapter identity/health, port collision state, visible and unexposed host counts, the last startup or routing error, Connection Descriptor and diagnostic locations, and a copyable diagnostic summary.
- Provide corresponding client-safe health and discovery facts so an agent can distinguish no exposed target, incompatibility, endpoint failure, and port collision. Repair is explicit; there is no automatic configuration edit, runtime switch, download, endpoint change, or other silent fallback.
- Show storage agreement and failures under the status and host-isolation rules in [Reconcile the per-user storage root across topology, installation, and Forensic Record decisions](13-reconcile-storage-root.md), which owns the shared root-resolution contract.
- A supported uninstall removes the extension and bundled adapter and immediately removes the Connection Descriptor so clients cannot discover a nonexistent endpoint. Bounded diagnostics and per-user settings remain for troubleshooting or reinstall. A separately confirmed **Reset Revit MCP data** action, available only while the adapter is stopped, removes those settings, diagnostics, and any retained support/runtime artifacts.
