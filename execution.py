"""Deliberately explicit integration boundary for hardware write operations."""
import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone


@contextmanager
def operation_lock(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


class Executor:
    """A site verifier implements verify(plan, completed_steps) and verify_result(plan).

    verify must re-read hardware, resolve current controller index -> expected
    serial and channel/id -> expected disk serial, and prove EVERY requirement.
    It returns a set of requirement names, or raises. No built-in 'trust me' flag.
    Result verification must wait for asynchronous controller work to finish.
    A failure/timeout stops the sequence. Never automatically replay a write.
    """
    def __init__(self, runner, verifier, audit, lock_path):
        self.runner, self.verifier = runner, verifier
        self.audit, self.lock_path = audit, lock_path

    def _event(self, plan, phase, step=None):
        self.audit({"time": datetime.now(timezone.utc).isoformat(), "operation": plan.operation,
                    "controller_serial": plan.target.serial, "phase": phase, "step": step})

    def execute(self, plan, *, confirmation, keys=None):
        if confirmation != plan.target.serial:
            raise PermissionError("Confirmation must match expected controller serial")
        with operation_lock(self.lock_path):
            self._execute_locked(plan, keys)

    def execute_workflow(self, workflow, *, confirmation, keys=None):
        if not workflow.stages or any(p.target.serial != confirmation for p in workflow.stages):
            raise PermissionError("Confirmation must match every stage controller serial")
        with operation_lock(self.lock_path):
            for plan in workflow.stages:
                # Postconditions (including asynchronous completion) are barriers.
                self._execute_locked(plan, keys)

    def _execute_locked(self, plan, keys):
        self._event(plan, "started")
        try:
            for index, command in enumerate(plan.commands):
                proven = set(self.verifier.verify(plan, index))
                missing = set(plan.requirements) - proven
                if missing:
                    raise PermissionError("Unproven preconditions: " + ", ".join(sorted(missing)))
                self._event(plan, "step-started", index)
                self.runner.run(command, keys=keys)
                self._event(plan, "step-returned", index)
            if self.verifier.verify_result(plan) is not True:
                raise RuntimeError("Postcondition not verified")
            self._event(plan, "verified")
        except Exception:
            self._event(plan, "stopped-inspect-before-retry")
            raise
