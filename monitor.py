"""Read-only polling daemon with atomic JSON state for other software."""
import json
import os
import signal
import tempfile
import threading
from pathlib import Path
from datetime import datetime, timezone
from .runner import InvalidArgumentsError
from .arcconf import Arcconf
from .inventory import normalize
from .mirror import read_md


def atomic_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".status-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def snapshot(client, adapter, md_name):
    result = {"schema_version": 1, "observed_at": datetime.now(timezone.utc).isoformat(),
              "ok": False, "safe_to_pull": False, "errors": []}
    try:
        result["inventory"] = normalize(client.inventory(), adapter)
    except InvalidArgumentsError as exc:
        result["errors"].append({"source": "arcconf", "type": type(exc).__name__,
                                 "reported_controller_count": exc.reported_controller_count})
    except Exception as exc:
        result["errors"].append({"source": "arcconf", "type": type(exc).__name__})
    try:
        result["mirror"] = read_md(md_name)
    except Exception as exc:
        result["errors"].append({"source": "md", "type": type(exc).__name__})
    result["ok"] = not result["errors"]  # collection success, NOT array health
    return result


def serve(client, adapter, md_name, output, interval=10):
    if interval <= 0:
        raise ValueError("Positive polling interval required")
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        state = snapshot(client, adapter, md_name)
        atomic_json(output, state)
        print(json.dumps({"observed_at": state["observed_at"], "ok": state["ok"],
                          "errors": state["errors"]}), flush=True)
        stop.wait(interval)
