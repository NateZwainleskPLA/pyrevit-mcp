# Choose the host listener lifecycle after the Routes reload failure

Type: prototype
Status: open
Blocked by: none

## Question

Can the extension obtain a reliable host listener lifecycle from pyRevit Routes across startup and reload on the chosen baseline, or must the Target Runtime own a listener (or require a validated upstream fix)? Decide the smallest supported contract before migration sequencing is finalized.

Start from [Prototype the in-Revit execution lane and control plane over pyRevit Routes](17-prototype-host-execution-lane.md#answer) and its local `prototype/host-execution-lane` evidence at commit `e808d07e7d12876c974e3e084cb5dfe101aa5cc6`. The private event/registry worked, but after one full reload the first state GET succeeded and subsequent calls timed out. An unknown route and native `/routes/sisters` also timed out with zero response bytes; a later reload restored responsiveness. A separate initial production-route timeout contained disposed-socket errors. Do not assume these observations share a cause. The closed-Document snapshot defect was confined to the probe and was corrected and rechecked separately.

Build a minimal, model-free reload reproducer and distinguish server/thread/socket lifetime, route registration, engine/callback lifetime, and logging failures. Record the actually loaded source and binaries. Avoid inferring stock-release behavior from the mixed development environment. Keep any code throwaway; this ticket decides the listener seam and support requirements, rather than implementing the migration or broadly repairing the pyRevit fork.

Compare only demonstrated options: extension-only use of existing Routes with verified lifecycle rules, a concrete pyRevit baseline fix that can satisfy the release policy, or an extension-owned listener behind the already replaceable Target Runtime interface. Preserve loopback/trust rules, native sibling-discovery compatibility where retained, startup-created private execution events, bounded control access, and target-generation expiry with no operation recovery/replay.

Prefer retaining Routes through a focused upstream pyRevit contribution if the investigation confirms an upstream defect and a practical fix. Treat an extension-owned listener as the fallback. Establish a minimal reproducer on the relevant baseline before attributing the failure upstream; distinguish defects confined to the custom checkout or probe. If an upstream fix is needed, identify its scope, regression evidence, and implications for the release-time pyRevit minimum. An upstream contribution remains an implementation handoff from this planning ticket, not an assumed accepted or released dependency.

User direction, 2026-09-09: willing to contribute to pyRevit to fix Routes if necessary. This guides the investigation without settling the cause or listener choice.

Specify startup/reload/disable/exit ownership, liveness checks, failure reporting and containment, and any amendments needed to topology, installation, execution safety, or acceptance evidence. Repeat controls while a UI operation and a native pick are active if the chosen change affects those paths. Do not use arbitrary STA sleeps as evidence of ordinary UI responsiveness or silently introduce message pumping without considering reentrancy. The human participates in live reload/interaction checks; unsupported cases must be explicit.
