# Decide the fate of the Revit launch and installation-discovery tools

Type: grilling
Status: resolved
Assignee: NateZwainleskPLA
Blocked by: none

## Question

Where, if anywhere, do `launch_revit` and `list_revit_installations` live in the target architecture?

Three resolved decisions conflict. **Define Revit Target and Document Target identity semantics** names launching Revit a workstation action that needs no target. **Choose MCP adapter topology and durable state ownership** says the Streamable HTTP adapter exists only while a Revit Host is live, never cold-starts Revit, and leaves cold start to "an isolated legacy or bootstrap concern". **Define the legacy compatibility and cutover contract** then removes every legacy path. The current tools (`tools/launch_tools.py`, documented in the README) therefore have no home.

Decide one of: drop the launch tools from the product; keep them only in the client-spawned stdio form of the same server; allow the adapter to be started by a client with zero hosts so it can launch Revit and then hand off to host-cooperative lifetime; or something else. The answer must state how a launched Revit becomes a Revit Host and an exposed Revit Target under the per-user default of do-not-expose, and must amend the conflicting sentences in the three tickets above.

## Comments

- 2026-09-09: Asked whether agents should retain installation discovery and Revit launch with no running instance, recommending preservation through explicit client startup of the bundled adapter while respecting the existing exposure preference. User answered: "yes, but as a configurable setting defaulting to no." Cold-start support is retained as an opt-in capability, disabled by default; the precise setting scope and adapter lifetime remain to be settled.
- 2026-09-09: User confirmed installation listing is always allowed, launch permission belongs behind a user setting, and accepted the proposed adapter lifetime: "listing installed versions should just be allowed, launching revit permissions behind user setting> 3 sounds good."

## Answer

### Retained tools and launch permission

- Retain `list_revit_installations` and `launch_revit` as workstation-scoped tools in the same server and deterministic catalog for HTTP, stdio, and every supported protocol era. Neither requires a Revit Target or Document Target, and neither depends on an existing Revit Host.
- Installation discovery is always available when the adapter is reachable. It does not require launch permission or host exposure.
- Add the persisted per-user **Allow agents to launch Revit** setting, defaulting to **off**. It gates every agent-requested launch, including additional instances while another Revit Host is already running. A disabled setting produces an explicit refusal without starting a process; it does not remove the tool from the catalog.
- The user changes launch permission through local configuration or the Revit MCP Status surface. MCP calls cannot enable it. Starting the adapter, discovering installations, or enabling host exposure does not implicitly enable launch permission.

### Adapter startup and lifetime

- The bundled helper supports explicit client startup with zero Revit Hosts. HTTP startup uses the same per-user launch mutex, stable endpoint, adapter identity and compatibility checks, and port-collision behavior as host startup. A compatible existing adapter is reused. This is a startup path for the same product, not a legacy executable or separately installed service.
- A client-started HTTP adapter with no hosts gets a configurable startup window, defaulting to **five minutes**. It remains alive beyond that window while a launch is pending. If no host arrives and no launch remains pending, it exits when the startup window has elapsed.
- When the extension loads in a Revit process, the adapter adopts normal host-cooperative lifetime: hosts keep it available regardless of exposure, and after the last host disappears it uses the topology's normal configurable no-host grace period.
- The optional stdio form lives with its client rather than adopting the HTTP host-lifetime rule. Host-side operations retain their previously defined independence from the adapter.
- Starting the adapter never launches Revit by itself. A separate `launch_revit` call must pass the launch-permission check.

### From launched process to exposed target

- Starting `Revit.exe` alone creates neither a Revit Host nor a Revit Target. The installed and enabled pyRevit extension must load and register its runtime for that process to become a Revit Host. Launch does not install or enable the extension or pyRevit on the user's behalf.
- A newly loaded host follows the existing persisted future-host exposure default, which is **do not expose** on a new installation. If that default remains off, the host is unexposed until the user enables it locally; if the user has enabled automatic exposure, normal target registration proceeds. Launch permission never overrides this independent preference.
- A client must discover and explicitly select an exposed Revit Target before submitting target-bound work. A launched process, a responding Routes endpoint, and an exposed target are distinct facts; launch must not imply that the new process is ready for model operations.

### Follow-through

- Amend [Define Revit Target and Document Target identity semantics](03-define-target-identity.md), [Choose MCP adapter topology and durable state ownership](04-choose-runtime-topology.md), [Choose the installation and runtime packaging contract](05-choose-installation-contract.md), and [Define the legacy compatibility and cutover contract](08-define-legacy-cutover.md) to reference this retained workstation capability and its startup exception.
- [Define the explicit-target tool catalog and per-command declarations](15-define-tool-catalog.md) owns the exact bootstrap invocation, launch result and error schemas, bounded readiness observation, process correlation, and retry behavior for workstation launch. These cannot borrow target-owned operation guarantees before a Revit Target exists.
- This resolves product placement, permission, exposure, and adapter lifetime only. No migration code is implemented by this ticket.
