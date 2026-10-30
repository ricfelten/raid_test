# Buildroot and systemd

Include Python 3.9 or later with its standard library (`json`, `subprocess`,
`tempfile`, `threading`, `signal`, `fcntl`, `secrets`), mdadm, util-linux blockdev,
and the correct controller utility. Kernel requirements include MD/RAID1 and the
appropriate SmartRAID driver (confirm smartpqi support for the exact device),
plus the chosen filesystem and device discovery support. The application has no
third-party Python runtime dependencies.

The extracted x86-64 ARCCONF is dynamically linked and requests
`/lib64/ld-linux-x86-64.so.2`. Confirm its loader and shared libraries on your
Buildroot target; a musl image cannot be assumed compatible with a glibc vendor
binary. Check redistribution terms before including it in firmware. Do not run
an installer intended for a desktop distribution blindly on Buildroot.

Copy `canister/` into the target Python site-packages using a Buildroot package or
rootfs overlay. Alternatively build/install the pyproject package on a suitable
build host. Install the validated vendor executable as `/usr/sbin/arcconf`, a
real adapter as `/etc/canister/adapter.json`, and the sample unit as
`/etc/systemd/system/canister-monitor.service`.

```sh
systemctl daemon-reload
systemctl enable --now canister-monitor.service
systemctl status canister-monitor.service
journalctl -u canister-monitor.service
cat /run/canister/status.json
```

These are deployment instructions, not commands already run on your server.
Buildroot must be configured for systemd to use this unit. On BusyBox/SysV init,
run the same Python monitor command under the selected supervisor.

The monitor is read-only at the storage command level and runs as root because
ARCCONF requires it. Its status is mode 0600 in a 0750 runtime directory. If a
non-root application needs access, use a dedicated trusted group and deliberately
adjust file publication permissions in atomic_json and the service; avoid making
raw configuration broadly readable. It neither needs encryption keys nor performs
mutations. Keep any future write/BMC service separate and narrowly accessible.

The unit permits actual device visibility and a private temporary directory for
ARCCONF JSON files. Validate sandbox restrictions against the installed utility;
`nologs` is used to avoid vendor logs outside writable locations. Runtime output
is transient; use persistent storage for an eject transaction journal and audit.

MD boot assembly must be constrained to the commissioned active array and member
set. A returning exported canister has stale metadata and matching UUIDs: prevent
udev/mdadm auto-add or auto-assembly from treating it as authoritative. Establish
the platform-specific mdadm configuration and event rules in commissioning;
this project does not modify boot assembly or enable automatic degraded startup.

Command timeout defaults to 60 seconds. A timed-out mutation may continue in the
controller; inspect it. For polling, consumers should allow for command timeout
when deciding staleness but never infer physical safety from monitor JSON.
