# Canister rotation and front-panel button

Distinguish **bay** (physical socket), **controller** (card serial), and
**canister** (the removable set of drive serials). A controller number can change
across boots; a canister can move between controllers. Store all three identities
and the LD WWN / Linux by-id / MD UUID mapping. Never identify media only by sda
or controller 1.

## Preferred sequence: attach third, synchronize, export first

1. A and B are healthy hardware RAID 6 arrays and fully synchronized MD members.
   Ensure controller cache protection is healthy and drives honor flushes.
2. Insert empty C. Verify its identity and that it contains no data to preserve.
   Establish/recover its encryption keys. Create a matching-size RAID 6 logical
   disk. Wait for initialization and all background tasks to finish.
3. With a validated MD version, add C and grow the mirror from two active replicas
   to three. The `mirror-extend` plan expresses this. Wait for idle sync state,
   zero degraded count, and all three members in sync. Check hardware RAID health
   independently. A spare alone is NOT a third up-to-date mirror copy.
4. Operator presses A's button. Verify the complete identity chain, all health
   evidence and two surviving replicas. Deny if rebuilding, locked, unknown,
   stale, or degraded. Default `assess_eject` enforces two survivors.
5. Establish an application consistency point: checkpoint/quiesce databases,
   flush application buffers and freeze the filesystem briefly if appropriate.
   Recheck state while writes are held. A filesystem freeze stalls writes;
   whether that satisfies service availability requirements is application-specific.
6. Fail and remove A from MD, verify absence, and flush the detached block device
   plus controller cache using the documented hardware procedure. Resume writers
   through a guaranteed finally/context-manager path, even on failure.
7. Isolate the canister through the verified enclosure/BMC sequence. Do not assume
   an ARCCONF disk LED means safe removal. Verify no pending I/O or other users,
   and enclosure readiness. Only then light the safe-to-remove indicator.
8. Operator removes A. Confirm presence change. Reconcile MD geometry back to two
   active replicas if needed. `mirror-shrink` is a separate plan because valid
   slot placement must be checked; do not blindly shrink with an active member
   occupying a slot the kernel would discard. Record export ID, timestamp,
   canister/drive serials, MD UUID, key version and consistency method.
9. A is now the exported copy. Retain it until retrieval and integrity validation
   succeed. Only then authorize reset/reuse. Never erase on insertion or button press.

The coordinator in `workflow.py` provides this transaction's hook order. Its
journal must be durable, and the shared write lock must cover the whole operation.
An unfinished transaction after a crash is **uncertain**, not safe-to-remove.
Start with LEDs in a deny/fault state; reconcile from hardware instead of replaying
commands. No automatic recovery or reboot resumption is implemented.

## If removal must happen before insertion

A two-member mirror can continue on B after removing A. A+B redundancy is lost
until C has been fully rebuilt from B. `minimum_remaining=1` is an explicit
policy override, not the default. `mirror-add` fills the missing slot in this
mode. Do not use `--assume-clean`, forced assembly or a stale returning disk as
a source. Old exported copies must not be automatically re-added.

## Reading the exported copy

A detached MD member carries MD metadata, possibly a failed/member state and a
three-replica geometry. It is not a standalone filesystem at byte zero. Validate
an isolated, read-only recovery procedure using the actual MD version and
filesystem. Avoid production auto-assembly and avoid presenting two arrays with
the same MD/filesystem UUID on the same host. Use a separate retrieval system;
load required controller/SED keys and prevent all writes to the original export.
If normal read-only degraded assembly refuses the intentionally detached member,
work on a block clone and validate a recovery procedure there; do not improvise
`--force` against production or the only export. Test this before deployment.
Filesystem-specific no-recovery mount options and application recovery may be
needed. A live split without a consistency boundary is at best crash-consistent.
For uninterrupted writers, design and validate an application snapshot/export
path (possibly LVM/filesystem snapshots) rather than promising freeze-free
consistency from an MD split.

## Button / BMC integration

Obtain the motherboard/BMC vendor's wiring and event documentation. Possibilities
include BMC GPIO, an OEM IPMI event, a Redfish event, an enclosure management
controller, or a direct Linux GPIO input. There is no portable OEM command to
assume. Determine whether pressing the button currently cuts power immediately;
that behavior must be changed or interlocked before using this workflow.

A privileged adapter maps a known hardware event to a configured bay ID, debounces
it, and calls `ButtonRequests.request`. It submits an eject request only. Storage
code resolves identity and runs preflight. Indicator convention: amber while
preparing, green only after verified isolation, red on refusal/failure. A BMC
hardware interlock is preferable if the operator can otherwise pull at any time.

Do not allow arbitrary event payloads to select device paths or shell commands.
Authenticate remote BMC events and reject replays. Power-off, flush and latch
operations need vendor-specific implementation and lab validation. Removal of a
whole four-drive canister must be supported electrically by the backplane; the
fact that individual U.2/U.3 drives support hot plug is not sufficient evidence.
