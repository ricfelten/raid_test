"""Pure policy for a front-panel eject request. Never powers off hardware."""
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Decision:
    allowed: bool
    phase: str
    reasons: tuple

    def to_dict(self):
        return asdict(self)


def assess_eject(md, outgoing, healthy_devices, *, minimum_remaining=2,
                 fresh=False, identity_verified=False):
    """healthy_devices are kernel member names whose RAID6 health was verified.

    An allowed decision only permits STARTING the quiesce/detach transaction.
    It is never a safe-to-pull indication. Missing evidence denies the request.
    """
    reasons = []
    if minimum_remaining not in (1, 2):
        raise ValueError("minimum_remaining must be 1 or 2")
    if not fresh:
        reasons.append("fresh inventory required")
    if not identity_verified:
        reasons.append("canister/controller/LD/MD identity chain unverified")
    if not md.get("healthy") or md.get("level") != "raid1":
        reasons.append("mirror not healthy and idle")
    members = md.get("members", [])
    synchronized = {m["device"] for m in members if "in_sync" in m["state"]
                    and "faulty" not in m["state"]}
    if outgoing not in synchronized or outgoing not in healthy_devices:
        reasons.append("outgoing member is not a verified synchronized RAID6 copy")
    survivors = (synchronized & set(healthy_devices)) - {outgoing}
    if len(survivors) < minimum_remaining:
        reasons.append("insufficient healthy replicas after removal")
    return Decision(not reasons, "ready-to-quiesce" if not reasons else "blocked", tuple(reasons))


class ButtonRequests:
    """BMC adapters call request with a stable bay ID and monotonic timestamp.

    Debounces requests only. Hardware actions and LEDs belong to a commissioned
    BMC adapter, never to an untrusted event payload. State resets after reboot.
    """
    def __init__(self, bays, debounce_seconds=3):
        self.bays, self.debounce = frozenset(bays), debounce_seconds
        self.last = {}

    def request(self, bay, now):
        if bay not in self.bays:
            raise ValueError("Unknown bay")
        last = self.last.get(bay)
        if last is not None and now - last < self.debounce:
            return None
        self.last[bay] = now
        return {"event": "eject-requested", "bay": bay, "safe_to_pull": False}


class EjectCoordinator:
    """Site hooks own BMC, application quiesce, and verified storage operations.

    No default hooks exist: the enclosure's safe-removal sequence cannot be
    inferred from ARCCONF. Journal must durably record each transition. The
    caller must hold the same global operation lock as Executor. On restart,
    any unfinished transaction requires reconciliation; never auto-resume it.
    """
    def __init__(self, hooks, journal):
        self.hooks, self.journal = hooks, journal

    def eject(self, bay):
        self.journal(bay, "requested")
        try:
            decision = self.hooks.preflight(bay)
            if not decision.allowed:
                self.journal(bay, "blocked")
                return decision
            self.journal(bay, "quiescing")
            # Context must resume writers even if detach or flush fails.
            with self.hooks.quiesce(bay):
                if not self.hooks.preflight(bay).allowed:
                    raise RuntimeError("State changed while quiescing")
                self.journal(bay, "detaching")
                self.hooks.detach_and_verify(bay)
                self.hooks.flush_and_verify(bay)
            self.journal(bay, "isolating")
            self.hooks.isolate_and_verify(bay)
            # This must check member absence, all affected controllers, enclosure
            # state, and remaining replicas immediately before enabling the LED.
            if self.hooks.safe_to_remove(bay) is not True:
                raise RuntimeError("Physical removal not verified")
            self.journal(bay, "safe-to-remove")
            self.hooks.indicate_safe(bay)
            return Decision(True, "safe-to-remove", ())
        except Exception:
            self.journal(bay, "uncertain-manual-reconciliation-required")
            self.hooks.indicate_fault(bay)
            raise
