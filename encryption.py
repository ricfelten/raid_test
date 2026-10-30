"""SED key references and local credential-file provider; no keys in plans."""
import os
import re
import secrets
import stat
from pathlib import Path
from .plans import Plan, BASE
from .runner import Command, SecretRef


def validate_key(value):
    if not (8 <= len(value) <= 32 and value.isascii() and all(33 <= ord(c) <= 126 for c in value)
            and any(c.isupper() for c in value) and any(c.islower() for c in value)
            and any(c.isdigit() for c in value) and any(not c.isalnum() for c in value)):
        raise ValueError("SED key must be 8-32 printable ASCII characters with upper/lower/digit/symbol")
    return value


class FileKeys:
    """Use a private directory or systemd credentials, preferably tmpfs.

    This is an access-controlled file provider, NOT encrypted escrow or a KMS.
    Backups and recovery testing are mandatory before enabling encryption.
    """
    def __init__(self, directory):
        self.directory = Path(directory)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise PermissionError("Credential directory must be owned by service user and mode 0700")

    def _path(self, name):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise ValueError("Invalid key reference")
        return self.directory / name

    def read(self, name):
        fd = os.open(self._path(name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > 33:
                raise PermissionError("Key must be a private regular file owned by service user")
            return validate_key(source.read(34).rstrip("\n"))

    def generate(self, name):
        while True:
            key = "".join(secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#%+-_")
                          for _ in range(32))
            try:
                validate_key(key)
                break
            except ValueError:
                pass
        fd = os.open(self._path(name), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as destination:
            destination.write(key + "\n")
            destination.flush(); os.fsync(destination.fileno())
        return {"key_reference": name, "escrow_verified": False}


def enable_sed(target, key_name):
    return Plan("enable-sed", target, (Command("arcconf", ("SEDENCRYPTION", target.controller,
                "MODE", "enable", "KEYMANAGEMENTMODE", "local", "MASTERKEY", SecretRef(key_name),
                "noprompt", "nologs"), sensitive=True),),
                BASE + ("sed_supported", "entire_controller_in_maintenance", "escrow_and_recovery_verified"))


def rotate_sed(target, old_key, new_key):
    if old_key == new_key:
        raise ValueError("Use a new escrowed key reference")
    return Plan("rotate-sed-key", target, (Command("arcconf", ("SEDENCRYPTION", target.controller,
                "CHANGEMASTERKEY", "NEWMASTERKEY", SecretRef(new_key), "MASTERKEY", SecretRef(old_key),
                "noprompt", "nologs"), sensitive=True),),
                BASE + ("sed_supported", "entire_controller_in_maintenance", "escrow_and_recovery_verified"))


def import_sed(target, foreign_key):
    return Plan("import-sed", target, (Command("arcconf", ("SEDENCRYPTION", target.controller,
                "IMPORT", "device", *target.addresses(), "FOREIGNKEY", SecretRef(foreign_key),
                "noprompt", "nologs"), sensitive=True),),
                BASE + ("sed_supported", "foreign_media_identity_verified", "escrow_and_recovery_verified"))
