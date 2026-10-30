# Commissioning and execution contract

The project is an integration library, not a certified hot-swap controller.
The hardware-specific adapter and live acceptance tests are outstanding because
root discovery was unavailable and BMC/backplane details are unknown.

## Capture and mapping

Capture actual GETCONFIGJSON SCHEMA and ALL output from each installed firmware /
ARCCONF combination. Add anonymized fixtures and explicit field mappings. Do not
infer field identity from fuzzy string matches. Validate healthy/degraded/rebuild,
missing canister, locked SED, foreign media and controller renumbering captures.
If the real JSON uses dictionaries instead of arrays, implement an explicit
version-specific structural transform before calling `normalize`.

Configure bays separately from canisters. Bind controller serial and PCI address,
disk serial set, logical disk WWN, stable Linux block ID, capacity, sector size,
and MD UUID. A by-id path alone does not prove the whole chain. Store inventory
and commissioned compatibility data in root-owned configuration. No auto-discovery
result should automatically authorize reset or become a trusted replacement.

## Execute plans from site software

```python
from canister.execution import Executor
from canister.plans import raid6

plan = raid6(verified_target, size_mib=verified_common_size, encrypted=True)
# runner, site_verifier and durable_audit are supplied by the integration.
executor = Executor(runner, site_verifier, durable_audit, '/run/canister/operations.lock')
executor.execute(plan, confirmation=verified_target.serial, keys=credential_provider)
```

`site_verifier.verify(plan, completed_steps)` must return only requirement names
it has actually proven from fresh evidence. An implementation that simply returns
`plan.requirements` defeats the design and is not a valid verifier. It must:

- Match current controller number to expected serial and each drive address to
  its expected serial. Refuse changed topology or ambiguous ownership.
- Check installed tool, driver, firmware and capability allowlist, and hardware
  job state. Serialize with other storage managers or disable them.
- Resolve Linux block topology (whole disk, partitions, MD/LVM/dm holders), mounts
  across relevant namespaces, swap and other application users. Refuse any use
  for reset, format, reversion or mirror creation. Maintenance must control races
  with automount and concurrent external tools; the library lock is cooperative.
- Prove selected LDs use only selected drives and that deletion cannot affect a
  peer array. No controller-wide ALL commands are generated.
- Check key recovery, capacity, sector size, health, cache protection and every
  other named plan requirement. Mirror plans also require the expected MD UUID.
- For multi-step operations, validate the expected intermediate state at each
  step, using completed_steps and fresh hardware. Some prerequisites describe
  the state before the first step; record that evidence in the locked transaction
  and prove the intended transition, rather than requiring a detached disk still
  be in the mirror or a deleted LD still exist.

`verify_result(plan)` must return literal True only after polling asynchronous
jobs to completion with a deadline and verifying the intended hardware state.
No success marker, command exit code, or submitted job means rebuild is complete.
Timeouts are uncertain outcomes: inspect state and create a new deliberate plan;
never blindly replay. The library provides no automatic rollback for data loss.

The audit callback must synchronously persist events without secrets and fail
closed if durable recording is unavailable. Audit is not a replay journal.
EjectCoordinator uses a separate persistent transition journal and the same
operation lock. Its hooks must support quiesce cleanup, verified detach/flush,
isolation and BMC indication. They must not enable a green LED from cached state.

## Hardware acceptance

Use disposable drives/data and prove: initial creation, full build, read/write
integrity, two/three-member MD behavior, planned removal, surprise removal,
rebuild, swapped/renumbered controllers, wrong canister, wrong key, full key
recovery on another controller, degraded RAID6 under a healthy MD layer, stale
monitor data, repeated button presses, BMC loss, concurrent requests and process
termination between every write step. Verify no safe indication after failure or
restart without reconciliation. Confirm exported-copy read-only recovery and
application consistency before accepting the concept of operations.

Test physical canister hot removal under sustained I/O with the chassis vendor.
Measure rebuild duration and application latency at intended fill/capacity; 16 TB
labels and premium hardware do not predict full-array resync time.

## Staged lifecycle verification

For `Executor.execute_workflow`, the same lock spans all stage executions and
postcondition waits. Implement each lifecycle requirement as an actual check;
policy names and manifests are not evidence. Provisioning postconditions must
verify ownership, encrypted RAID6 build completion, then full MD synchronization.
Reader stage postconditions must verify source read-only state; examine metadata
against the trusted export log; call `verify_readonly_md` after assembly and just
before mount; and check the resulting mount type/UUID and ro/no-replay flags.

The close-reader plan rechecks expected intermediate state after unmount before
stopping MD. Any timeout/failure leaves the session for deliberate reconciliation,
not automatic force/repair/rollback. Preserve source read-only state on failures.
