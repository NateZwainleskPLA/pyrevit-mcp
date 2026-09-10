# Decide product ownership, signing identity, and upstream relationship

Type: grilling
Status: resolved
Assignee: NateZwainleskPLA
Blocked by: none

## Question

Who owns and signs this product, and is it a fork-only product or an upstream contribution?

The installation and acceptance contracts require a signed Windows-x64 helper with no waiver, so a code-signing identity gates the "Implementation accepted" gate. Nothing on the map says whether that identity is an organisation certificate or a personal one, who holds the private key, and where release builds run. The extension manifest still points at the community upstream repository while the working remote is a personal fork; a signed 22 MiB binary inside an extension repository is unlikely to be acceptable upstream.

Decide: fork-only versus upstream intent; the signing identity and key custody; whether an unsigned developer build is permitted before release; and the resulting changes to the extension manifest, Notes, and Out of scope. Obtaining the certificate itself becomes a follow-up task once the identity is chosen.

## Comments

- User direction: this work is intended to be upstreamed. Upstream should be responsible for maintenance, releases, and signing. Nate may participate in maintenance but is not committing to that responsibility.
- This records the intended ownership model, not an agreement already obtained from upstream. Upstream acceptance of release ownership, signing identity, key custody, and the release build path remains to be established.
- Pending proposal for the next discussion round: permit explicitly enabled unsigned developer builds; require upstream-controlled signing and release infrastructure for production; retain upstream product identity and attribution in the extension manifest; exclude an independently maintained fork release from this effort. Capture upstream agreement and concrete release arrangements in a follow-up ticket rather than assume them.
- User confirmed the proposal and explicitly stated that developer builds are necessary.

## Answer

### Upstream intent and responsibility

This migration is intended as a contribution to the community upstream product. The personal fork is the development vehicle. Upstream maintainers are the intended owners of ongoing maintenance, production releases, the signing identity, signing-key custody, and the release build infrastructure. Nate may contribute to maintenance but has not committed to being the maintainer or release operator. Neither Nate nor PLA Designs is assigned a certificate purchase or signing obligation by this decision.

This is the agreed contribution policy, not evidence that upstream has accepted those responsibilities. [Establish upstream release ownership and signing arrangements](21-establish-upstream-release-arrangements.md) must obtain and record that agreement and the concrete publisher, custody, build, and distribution arrangements. No personal signing identity or independently maintained fork release is an automatic fallback if upstream declines; that would require revisiting the scope.

### Development and production builds

Unsigned developer builds are necessary and permitted before production, through an explicit developer opt-in. They must be identifiable as development artifacts and cannot satisfy the signed production acceptance gate. Missing or invalid production signatures must not silently enable developer mode. This exception does not relax target identity, execution safety, compatibility, or the other behavioral contracts.

[Define the migration sequence and rollback checkpoints](11-define-migration-sequence.md) will allocate the checks applicable to each development checkpoint. Production remains subject to the signed, self-contained Windows-x64 packaging contract and the full implementation acceptance gate. Upstream agreement and signing readiness gate production release; development can proceed while those arrangements are pending.

### Manifest, scope, and handoff

Retain upstream product identity, repository URL, and existing attribution in the extension manifest. The fork remote alone does not justify changing those fields. Any description or contributor metadata changes belong to the eventual upstream implementation and review; this planning ticket makes no runtime or manifest edit.

The map records this policy by reference and excludes an independently maintained fork distribution. The former certificate/build-path fog becomes the follow-up task linked above. That task establishes the arrangements needed to finish the specification; purchasing or provisioning signing credentials and implementing release automation belong to the implementation handoff, beyond this planning map's destination.
