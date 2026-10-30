# Encryption and key lifecycle

Selected policy: one shared SED master key across field and home controllers.
Generate it once; distribute the same secret securely. Follow
[shared-key workflows](shared-key-workflows.md) for provisioning and retrieval.

First identify the drive security standard, controller model, firmware, encryption
license/mode and supported command families. A self-encrypting drive's internal
media encryption is not evidence that access control is enabled. SED locking and
maxCrypto controller-based encryption are distinct. Avoid enabling both without
a tested recovery design.

The current wrappers implement documented SED local-key enable, master-key
rotation, foreign-drive key import, and factory revert command plans. They do
not provision maxCrypto, a KMIP server, OPAL users, controller passwords, PSID
recovery, or remote key-server certificates. Those need a model-specific adapter.

## Local provider

```sh
install -d -m 0700 /secure-runtime/canister-keys
python3 -m canister key-generate --directory /secure-runtime/canister-keys rotation-system-v1
python3 -m canister plan sed-enable --target examples/target.synthetic.json --key rotation-system-v1
```

The first command is an example site path, not created by this project. FileKeys
generates a 32-character random key meeting the supplied manual's SED constraints,
uses exclusive creation and mode 0600, refuses symlinks, and never returns key
bytes from generation. Read access should be limited to the execution service.
Keys are plaintext in these access-controlled files; this is not encrypted escrow.
Use a protected runtime directory, systemd credentials where compatible, TPM-backed
provisioning or a KMS-backed provider implementing `read(name)`.

Plans contain SecretRef names. Actual secrets are resolved only immediately before
execution. Runner does not print child output for secret commands and does not
include argv/output in exceptions. ARCCONF's documented syntax passes secrets in
argv: **privileged process inspection can still see them**, and Python does not
promise memory zeroization. `nologs` reduces utility logging but cannot guarantee
firmware or OS audit behavior. Restrict host access and process visibility; if
argv exposure is unacceptable, use a supported remote-key-management deployment
instead of this local transport. Never paste literal keys into CLI/history.

## Lifecycle

1. Generate a key reference and record controller/canister/drive identities.
2. Escrow it off the server with authenticated access and encrypted backups.
3. Prove restore on an isolated retrieval controller before enabling encryption.
4. Enable supported SED mode, create encrypted logical disks explicitly, and verify
   locking/encryption status from hardware. A successful command alone is not proof.
5. Record key version with each exported canister. Changing a controller key may
   affect all its managed drives, not just the target's four disks; the verifier
   must put the entire affected controller in maintenance.
6. For rotation, escrow the new key first, keep the old key, rotate, and verify
   read/unlock and recovery. Keep old keys as long as offline canisters/backups
   might require them. Never delete a key merely because online rotation succeeded.
7. Import foreign encrypted media only after serial verification. Do not take
   ownership or factory-revert media that contains an export to preserve.
8. Destroy media keys only after the retention policy explicitly authorizes
   cryptographic erasure and all retained copies are accounted for.

The executor requires `escrow_and_recovery_verified` but cannot verify an external
escrow itself. The commissioning verifier must supply that evidence. Key files
must never reside exclusively on the array they unlock. Tests use temporary keys,
not operational keys; no production encryption was enabled in this session.
