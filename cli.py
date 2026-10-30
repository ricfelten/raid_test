import argparse
import json
import sys
from pathlib import Path
from .captures import inspect_capture
from .arcconf import Arcconf
from .inventory import normalize, parse_json
from .runner import Runner
from .plans import Target, raid6, reset_metadata, sed_factory_revert
from .mirror import read_md, mirror_plan
from .encryption import FileKeys, enable_sed, rotate_sed, import_sed
from .monitor import serve, snapshot
from .lifecycle import SharedKeyPolicy, commission_shared_key, provision_canister
from .retrieval import ExportManifest, retrieve_canister, close_retrieval


def load(path):
    return json.loads(Path(path).read_text())


def main(argv=None):
    parser = argparse.ArgumentParser(description="Canister inventory and reviewable operation plans")
    parser.add_argument("--arcconf", default="/usr/sbin/arcconf")
    sub = parser.add_subparsers(dest="action", required=True)
    inspect_cmd = sub.add_parser("inspect-capture", help="Classify a saved schema, JSON candidate or diagnostic")
    inspect_cmd.add_argument("path")
    capture = sub.add_parser("capture", help="Read raw JSON (may contain sensitive configuration)")
    capture.add_argument("kind", choices=("inventory", "schema"))
    normalize_cmd = sub.add_parser("normalize")
    normalize_cmd.add_argument("capture"); normalize_cmd.add_argument("--adapter", required=True)
    md = sub.add_parser("md-status"); md.add_argument("--md", default="md0")
    for name in ("status", "monitor"):
        cmd = sub.add_parser(name); cmd.add_argument("--adapter", required=True)
        cmd.add_argument("--md", default="md0")
        if name == "monitor":
            cmd.add_argument("--output", required=True); cmd.add_argument("--interval", type=float, default=10)
    plan = sub.add_parser("plan", help="Generate commands only; never executes mutations")
    plan.add_argument("operation", choices=("raid6", "reset", "sed-revert", "sed-enable", "sed-rotate",
                                          "sed-import", "mirror-create", "mirror-add", "mirror-extend",
                                          "mirror-detach", "mirror-shrink"))
    plan.add_argument("--target", required=True)
    plan.add_argument("--size-mib", type=int); plan.add_argument("--encrypted", action="store_true")
    plan.add_argument("--logical-id", type=int, action="append")
    plan.add_argument("--md-device", default="/dev/md0"); plan.add_argument("--uuid")
    plan.add_argument("--member", action="append", default=[])
    plan.add_argument("--key"); plan.add_argument("--new-key")
    for name in ('plan-commission', 'plan-provision', 'plan-retrieve', 'plan-close-retrieval'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--target', required=True)
        if name != 'plan-close-retrieval':
            cmd.add_argument('--policy', required=True)
        if name in ('plan-provision', 'plan-retrieve'):
            cmd.add_argument('--member', required=True)
        if name == 'plan-provision':
            cmd.add_argument('--size-mib', type=int, required=True)
            cmd.add_argument('--uuid', required=True)
            cmd.add_argument('--mode', choices=('extend', 'add'), default='extend')
        if name != 'plan-commission':
            cmd.add_argument('--md-device', default='/dev/md0' if name == 'plan-provision' else '/dev/md127')
        if name in ('plan-retrieve', 'plan-close-retrieval'):
            cmd.add_argument('--mountpoint', default='/mnt/canister-export')
        if name == 'plan-retrieve':
            cmd.add_argument('--manifest', required=True)
            cmd.add_argument('--foreign-import', action='store_true')
    key = sub.add_parser("key-generate"); key.add_argument("--directory", required=True); key.add_argument("name")
    args = parser.parse_args(argv)
    client = Arcconf(Runner(arcconf=args.arcconf))
    try:
        if args.action == "inspect-capture":
            result = inspect_capture(Path(args.path).read_text())
        elif args.action == "capture":
            result = getattr(client, args.kind)()
        elif args.action == "normalize":
            result = normalize(parse_json(Path(args.capture).read_text()), load(args.adapter))
        elif args.action == "md-status":
            result = read_md(args.md)
        elif args.action == "status":
            result = snapshot(client, load(args.adapter), args.md)
        elif args.action == "monitor":
            serve(client, load(args.adapter), args.md, args.output, args.interval)
            return 0
        elif args.action == "key-generate":
            result = FileKeys(args.directory).generate(args.name)
        elif args.action.startswith('plan-'):
            spec = load(args.target)
            target = Target(spec['controller'], spec['serial'], tuple(tuple(d) for d in spec['disks']))
            if args.action == 'plan-close-retrieval':
                result = close_retrieval(target, args.md_device, args.mountpoint)
            else:
                policy = SharedKeyPolicy.from_dict(load(args.policy))
                if args.action == 'plan-commission':
                    result = commission_shared_key(target, policy)
                elif args.action == 'plan-provision':
                    result = provision_canister(target, policy, args.size_mib, args.member,
                                               args.md_device, args.uuid, args.mode)
                else:
                    manifest = ExportManifest.from_dict(load(args.manifest))
                    result = retrieve_canister(target, policy, manifest, args.member, args.md_device,
                                               args.mountpoint, foreign_import=args.foreign_import)
            result = result.to_dict()
        else:
            spec = load(args.target)
            target = Target(spec["controller"], spec["serial"], tuple(tuple(d) for d in spec["disks"]))
            if args.operation == "raid6":
                result = raid6(target, args.size_mib, args.encrypted)
            elif args.operation == "reset":
                result = reset_metadata(target, args.logical_id or [])
            elif args.operation == "sed-revert":
                result = sed_factory_revert(target)
            elif args.operation.startswith("mirror-"):
                result = mirror_plan(target, args.operation[7:], args.md_device, args.member, expected_uuid=args.uuid)
            else:
                if not args.key or (args.operation == "sed-rotate" and not args.new_key):
                    raise ValueError("Key references required")
                if args.operation == "sed-enable":
                    result = enable_sed(target, args.key)
                elif args.operation == "sed-rotate":
                    result = rotate_sed(target, args.key, args.new_key)
                else:
                    result = import_sed(target, args.key)
            result = result.to_dict()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if not (args.action == "status" and not result["ok"]) else 1
    except Exception as exc:
        # Exception text from site integrations may include secret material.
        print(json.dumps({"error": type(exc).__name__, "message": "Operation failed; check configuration and hardware state"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
