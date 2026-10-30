"""Shared-key commissioning and staged provisioning of empty canisters."""
import re
from dataclasses import dataclass, replace
from .plans import Plan, BASE, raid6
from .runner import Command
from .encryption import enable_sed
from .mirror import mirror_plan


@dataclass(frozen=True)
class SharedKeyPolicy:
    key_reference: str
    key_version: str

    def __post_init__(self):
        for value in (self.key_reference, self.key_version):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
                raise ValueError('Use non-secret key reference/version identifiers')

    @classmethod
    def from_dict(cls, data):
        if set(data) != {'key_reference', 'key_version'}:
            raise ValueError('Policy must contain only key_reference and key_version')
        return cls(**data)

    @property
    def requirement(self):
        # A label alone is not evidence. Site verifier must check commissioning
        # records and credential recovery, never infer equality from a label.
        return 'shared_sed_key_verified=' + self.key_reference + ':' + self.key_version


@dataclass(frozen=True)
class Workflow:
    operation: str
    stages: tuple

    def to_dict(self):
        return {'operation': self.operation, 'stages': [s.to_dict() for s in self.stages],
                'execution': 'verify each stage to completion before starting the next; no automatic retries'}


def commission_shared_key(target, policy):
    """One-time setup only; never re-enable/rekey a working controller on insertion."""
    plan = enable_sed(target, policy.key_reference)
    return replace(plan, operation='commission-shared-sed-key', requirements=plan.requirements + (
        'controller_sed_unconfigured', 'shared_key_escrow_version=' + policy.key_version))


def provision_canister(target, policy, size_mib, member, md_device, md_uuid, mode='extend'):
    """Requires an already commissioned controller. No erase/reset fallback."""
    if len(target.disks) != 4:
        raise ValueError('This canister design requires four drives')
    if mode not in ('add', 'extend'):
        raise ValueError('Use extend for a third replica or add for a missing replica')
    ownership = Plan('secure-new-canister', target, (Command('arcconf', (
        'SEDENCRYPTION', target.controller, 'TAKEOWNERSHIP', 'device', *target.addresses(),
        'noprompt', 'nologs')),), BASE + (policy.requirement, 'sed_supported',
        'four_factory_state_drives_no_data', 'matching_supported_sed_type', 'escrow_and_recovery_verified'))
    create = raid6(target, size_mib, encrypted=True)
    create = replace(create, requirements=create.requirements + (policy.requirement,
        'selected_drives_secured_with_shared_key', 'maxcrypto_not_enabled'))
    attach = mirror_plan(target, mode, md_device, [member], expected_uuid=md_uuid)
    attach = replace(attach, requirements=attach.requirements + (policy.requirement,
        'new_ld_wwn_bound_to_selected_drives', 'raid6_initialization_completed',
        'sed_encryption_verified_on_all_four_drives'))
    return Workflow('provision-new-canister', (ownership, create, attach))
