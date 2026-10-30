"""Linux MD status and explicit RAID1 command plans."""
import re
from pathlib import Path
from .runner import Command
from .plans import Plan


def read_md(name="md0", sys_root="/sys/class/block"):
    if not re.fullmatch(r"md[0-9]+", name):
        raise ValueError("Use the kernel MD name, e.g. md0")
    base = Path(sys_root) / name / "md"
    def read(field):
        return (base / field).read_text().strip()
    members = []
    for member in sorted(base.glob("dev-*")):
        members.append({"device": member.name[4:],
                        "state": (member / "state").read_text().strip().split(","),
                        "slot": (member / "slot").read_text().strip(),
                        "block_path": str((member / "block").resolve())})
    result = {"name": name, "uuid": read("uuid"), "level": read("level"),
              "array_state": read("array_state"), "raid_disks": int(read("raid_disks")),
              "degraded": int(read("degraded")), "sync_action": read("sync_action"),
              "sync_completed": read("sync_completed"), "members": members}
    result["healthy"] = (result["level"] == "raid1" and result["raid_disks"] >= 2 and result["degraded"] == 0
                         and result["sync_action"] == "idle"
                         and result["array_state"] in ("clean", "active", "active-idle")
                         and len([m for m in members if "in_sync" in m["state"]
                                  and "faulty" not in m["state"]]) == result["raid_disks"])
    return result


def _device(path):
    if not isinstance(path, str) or not path.startswith("/dev/disk/by-id/") or not path[16:] or "/" in path[16:] or ".." in path:
        raise ValueError("Use a stable /dev/disk/by-id/<id> device path")
    return path


def mirror_plan(target, action, md_device, members, *, expected_uuid=None):
    """Plans require a site verifier to bind each by-id to the target/peer LD.

    extend adds a spare then grows a two-member RAID1 to three replicas.
    detach deliberately leaves degraded geometry; shrink is a separate action
    after confirming the absent slot and two remaining synchronized replicas.
    """
    if not re.fullmatch(r"/dev/md[0-9]+", md_device):
        raise ValueError("Expected kernel MD path, e.g. /dev/md0")
    devices = tuple(_device(p) for p in members)
    if len(set(devices)) != len(devices):
        raise ValueError("Duplicate mirror devices")
    requirements = ("validated_controller_firmware_cli", "fresh_serial_binding", "exclusive_maintenance",
                    "stable_block_identity_and_capacity", "no_external_md_manager")
    if action == "create":
        if len(devices) != 2:
            raise ValueError("Create requires exactly two devices")
        commands = (Command("mdadm", ("--create", md_device, "--metadata=1.2", "--level=1",
                     "--raid-devices=2", "--bitmap=internal", *devices)),)
        requirements += ("both_raid6_ready", "devices_empty_unmounted_no_holders", "explicit_data_loss_ack")
    else:
        if not expected_uuid or not re.fullmatch(r"[a-fA-F0-9:-]+", expected_uuid):
            raise ValueError("Expected MD UUID required")
        requirements += ("md_uuid=" + expected_uuid,)
        if action in ("add", "extend"):
            if len(devices) != 1:
                raise ValueError("One incoming device required")
            commands = (Command("mdadm", ("--manage", md_device, "--add", *devices)),)
            requirements += ("incoming_raid6_ready", "incoming_empty_unmounted_no_holders",
                             "authoritative_online_source", "incoming_has_no_stale_md_metadata")
            if action == "extend":
                commands += (Command("mdadm", ("--grow", md_device, "--raid-devices=3")),)
                requirements += ("two_member_mirror_healthy_before_add",)
            else:
                requirements += ("two_member_mirror_has_exactly_one_missing_slot",)
        elif action == "detach":
            if len(devices) != 1:
                raise ValueError("One outgoing device required")
            commands = (Command("mdadm", ("--manage", md_device, "--fail", *devices)),
                        Command("mdadm", ("--manage", md_device, "--remove", *devices)),
                        Command("blockdev", ("--flushbufs", *devices)))
            requirements += ("eject_policy_passed_before_fail", "application_consistency_boundary_held",
                             "surviving_replicas_healthy", "outgoing_member_identity_verified")
        elif action == "shrink":
            if devices:
                raise ValueError("Shrink takes no device arguments")
            commands = (Command("mdadm", ("--grow", md_device, "--raid-devices=2")),)
            requirements += ("removed_third_member_slot_verified", "two_surviving_replicas_in_sync")
        else:
            raise ValueError("Unknown mirror action")
    return Plan("mirror-" + action, target, commands, requirements)
