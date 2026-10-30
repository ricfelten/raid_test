"""Reviewable operations, bound to expected controller and disk serials.

No plan is an authorization. Execution always requires a site verifier.
"""
from dataclasses import dataclass, asdict
from .runner import Command


@dataclass(frozen=True)
class Target:
    controller: int
    serial: str
    disks: tuple  # ((channel, id, serial), ...)

    def __post_init__(self):
        if type(self.controller) is not int or self.controller < 1 or not self.serial:
            raise ValueError("Controller index and serial are required")
        addresses, serials = set(), set()
        for channel, device, serial in self.disks:
            if type(channel) is not int or type(device) is not int or min(channel, device) < 0 or not serial:
                raise ValueError("Disk address and serial required")
            if (channel, device) in addresses or serial in serials:
                raise ValueError("Duplicate disk")
            addresses.add((channel, device)); serials.add(serial)
        if not self.disks:
            raise ValueError("Explicit disks required")

    def addresses(self):
        return tuple(n for ch, device, _ in self.disks for n in (ch, device))


@dataclass(frozen=True)
class Plan:
    operation: str
    target: Target
    commands: tuple
    requirements: tuple
    destructive: bool = True

    def to_dict(self):
        return {"operation": self.operation, "target": asdict(self.target),
                "commands": [c.display() for c in self.commands],
                "requirements": list(self.requirements), "destructive": self.destructive}


BASE = ("validated_controller_firmware_cli", "fresh_serial_binding", "exclusive_maintenance",
        "no_mounts_holders_or_swap", "not_an_active_mirror_member", "explicit_data_loss_ack")


def raid6(target, size_mib, encrypted=False):
    if len(target.disks) < 4:
        raise ValueError("RAID 6 requires at least four drives")
    if type(size_mib) is not int or size_mib <= 0:
        raise ValueError("Use a fixed positive MiB size shared by all canisters")
    if type(encrypted) is not bool:
        raise ValueError("encrypted must be boolean")
    args = ("CREATE", target.controller, "LOGICALDRIVE", "ENCODE", "enable" if encrypted else "disable",
            "METHOD", "BUILD", size_mib, "6", *target.addresses(), "noprompt", "nologs")
    requirements = BASE + ("all_selected_disks_unconfigured", "sufficient_capacity")
    if encrypted:
        requirements += ("encryption_enabled_and_recovery_tested",)
    return Plan("create-raid6", target, (Command("arcconf", args),), requirements)


def reset_metadata(target, logical_ids):
    """Deletes explicitly selected LDs and uninitializes selected disks; NOT sanitization."""
    ids = tuple(logical_ids)
    if not ids or any(type(i) is not int or i < 0 for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Explicit unique logical drive IDs required")
    commands = tuple(Command("arcconf", ("DELETE", target.controller, "LOGICALDRIVE", i,
                                          "noprompt", "nologs")) for i in ids)
    commands += (Command("arcconf", ("UNINIT", target.controller, *target.addresses(), "nologs")),)
    return Plan("reset-metadata", target, commands,
                BASE + ("logical_drives_use_exact_selected_disks", "no_other_arrays_on_selected_disks"))


def sed_factory_revert(target):
    return Plan("sed-factory-revert", target,
                (Command("arcconf", ("SEDENCRYPTION", target.controller, "REVERTTOOFS", "device",
                                     *target.addresses(), "noprompt", "nologs")),),
                BASE + ("sed_revert_supported_and_unlocked", "no_logical_drives_on_selected_disks"))
