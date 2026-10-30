"""Isolated retrieval: preserve export data; never force, repair, or create MD."""
import re
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from .plans import Plan
from .runner import Command
from .encryption import import_sed
from .mirror import _device
from .lifecycle import Workflow


@dataclass(frozen=True)
class ExportManifest:
    export_id: str
    drive_serials: tuple
    md_uuid: str
    filesystem: str
    filesystem_uuid: str
    key_version: str
    consistency: str
    layout: str = 'filesystem-on-md'

    def __post_init__(self):
        if len(self.drive_serials) != 4 or len(set(self.drive_serials)) != 4:
            raise ValueError('Four unique exported drive serials required')
        if any(not isinstance(s, str) or not s for s in self.drive_serials):
            raise ValueError('Drive serials must be nonempty strings')
        if not re.fullmatch(r'[0-9a-fA-F]{8}(?::[0-9a-fA-F]{8}){3}', self.md_uuid):
            raise ValueError('MD UUID must use the four-group mdadm format')
        if self.filesystem not in ('ext4', 'xfs') or self.layout != 'filesystem-on-md':
            raise ValueError('Only ext4 or XFS directly on MD is supported; no automatic LVM/LUKS/partition activation')
        if self.consistency not in ('application-quiesced', 'filesystem-frozen'):
            raise ValueError('A recorded export consistency boundary is required')
        for value in (self.export_id, self.filesystem_uuid, self.key_version):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
                raise ValueError('Invalid manifest identifier')

    @classmethod
    def from_dict(cls, data):
        return cls(**{**data, 'drive_serials': tuple(data['drive_serials'])})


def retrieve_canister(target, policy, manifest, member, md_device='/dev/md127',
                     mountpoint='/mnt/canister-export', *, foreign_import=False):
    if type(foreign_import) is not bool:
        raise ValueError('foreign_import must be boolean')
    if set(d[2] for d in target.disks) != set(manifest.drive_serials):
        raise ValueError('Target drives do not match the export manifest')
    if policy.key_version != manifest.key_version:
        raise ValueError('Select the archived policy/key version matching the export')
    _device(member)
    if not re.fullmatch(r'/dev/md[0-9]+', md_device):
        raise ValueError('Use a dedicated kernel MD device path')
    p = PurePosixPath(mountpoint)
    if not p.is_absolute() or '..' in p.parts or len(p.parts) < 3 or p.parts[1] != 'mnt':
        raise ValueError('Use a dedicated mountpoint below /mnt')
    base = ('validated_controller_firmware_cli', 'fresh_serial_binding', 'exclusive_maintenance',
            'isolated_retrieval_host', 'autoassembly_and_automount_disabled_before_insertion',
            'export_manifest_trusted=' + manifest.export_id, 'export_drives_match_manifest',
            policy.requirement, 'controller_has_no_other_attached_data',
            'no_background_controller_writes', 'original_export_never_used_for_repair')
    stages = []
    if foreign_import:
        # May modify security metadata: deliberately separate from host read-only access.
        imp = import_sed(target, policy.key_reference)
        stages.append(replace(imp, operation='import-exported-sed-security', requirements=base + (
            'foreign_sed_requires_explicit_import', 'foreign_key_matches_export',
            'no_interrupted_rekey', 'security_metadata_change_acknowledged',
            'no_mounts_holders_or_swap', 'not_an_active_mirror_member', 'escrow_and_recovery_verified')))
    protect = Plan('protect-export-block-device', target,
        (Command('blockdev', ('--setro', member)),), base + (
            'existing_raid6_unlocked_no_initialization', 'ld_wwn_bound_to_export_drives',
            'no_mounts_holders_or_swap'), destructive=False)
    # Inspection outputs must be re-read/verified by the verifier; never parsed as commands.
    examine = Plan('examine-export-member', target,
        (Command('mdadm', ('--examine', '--export', member)),), base + (
            'source_block_read_only_verified',), destructive=False)
    assemble = Plan('assemble-export-read-only', target,
        (Command('mdadm', ('--assemble', md_device, '--readonly', '--run',
            '--config=/dev/null', '--uuid=' + manifest.md_uuid, member)),), base + (
            'source_block_read_only_verified', 'md_uuid=' + manifest.md_uuid,
            'examined_metadata_1_2_raid1_no_reshape', 'export_event_count_and_role_verified',
            'no_active_array_with_export_uuid', 'retrieval_md_device_unused'), destructive=False)
    options = 'ro,noload,nodev,nosuid,noexec' if manifest.filesystem == 'ext4' else 'ro,norecovery,nodev,nosuid,noexec'
    mount = Plan('mount-export-read-only', target,
        (Command('mount', ('-t', manifest.filesystem, '-o', options, md_device, mountpoint)),), base + (
            'source_block_read_only_verified', 'md_block_read_only_verified',
            'md_state_readonly_no_resync_exact_export_member', 'md_uuid=' + manifest.md_uuid,
            'filesystem_uuid=' + manifest.filesystem_uuid, 'filesystem_type=' + manifest.filesystem,
            'filesystem_directly_on_md', 'mountpoint_empty_not_symlink_not_mounted'), destructive=False)
    return Workflow('retrieve-export-read-only', tuple(stages) + (protect, examine, assemble, mount))


def close_retrieval(target, md_device, mountpoint):
    if not re.fullmatch(r'/dev/md[0-9]+', md_device):
        raise ValueError('Expected kernel MD path')
    p = PurePosixPath(mountpoint)
    if not p.is_absolute() or '..' in p.parts or len(p.parts) < 3 or p.parts[1] != 'mnt':
        raise ValueError('Expected mountpoint below /mnt')
    return Plan('close-retrieval', target, (Command('umount', (mountpoint,)),
                Command('mdadm', ('--stop', md_device))),
                ('exclusive_maintenance', 'fresh_serial_binding', 'retrieval_session_identity_verified',
                 'mounted_export_matches_md_device', 'no_open_readers', 'source_block_read_only_verified'),
                destructive=False)


def verify_readonly_md(member, md_device, expected_uuid, sys_root='/sys/dev/block'):
    """Concrete Linux postcondition helper for the site's retrieval verifier.

    Recheck immediately before mounting. This verifies host block/MD protection,
    not the SED controller, export manifest, filesystem, or enclosure.
    """
    import os
    import stat
    from pathlib import Path
    paths = []
    for device in (member, md_device):
        info = os.stat(device)
        if not stat.S_ISBLK(info.st_mode):
            raise ValueError('Expected a block device')
        identity = '%d:%d' % (os.major(info.st_rdev), os.minor(info.st_rdev))
        paths.append((identity, Path(sys_root) / identity))
    (source_id, source), (_, array) = paths
    if (source / 'ro').read_text().strip() != '1' or (array / 'ro').read_text().strip() != '1':
        raise RuntimeError('Both source and MD must be block read-only')
    md = array / 'md'
    read = lambda name: (md / name).read_text().strip()
    actual_uuid = read('uuid').replace(':', '').replace('-', '').lower()
    wanted_uuid = expected_uuid.replace(':', '').replace('-', '').lower()
    if actual_uuid != wanted_uuid or not re.fullmatch('[0-9a-f]{32}', wanted_uuid):
        raise RuntimeError('Wrong MD UUID')
    if read('level') != 'raid1' or read('metadata_version') != '1.2':
        raise RuntimeError('Only RAID1 with metadata 1.2 is supported')
    if read('array_state') != 'readonly' or read('sync_action') != 'idle':
        raise RuntimeError('MD must be explicitly readonly with no recovery running')
    members = list(md.glob('dev-*'))
    if len(members) != 1 or (members[0] / 'block/dev').read_text().strip() != source_id:
        raise RuntimeError('MD must contain exactly the exported block device')
    return True
