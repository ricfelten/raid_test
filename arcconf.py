"""Read-only discovery; mutation builders live in plans.py and encryption.py."""
import tempfile
from pathlib import Path
from .runner import Command, Runner
from .inventory import parse_json


class Arcconf:
    def __init__(self, runner=None):
        self.runner = runner or Runner()

    def inventory(self, controller="ALL"):
        # Filename avoids utility banners and stdout redirection quirks.
        if controller != "ALL" and (not isinstance(controller, int) or controller < 1):
            raise ValueError("Expected ALL or positive controller index")
        with tempfile.TemporaryDirectory(prefix="canister-") as work:
            path = Path(work) / "inventory.json"
            self.runner.run(Command("arcconf", ("GETCONFIGJSON", controller, str(path), "nologs")))
            return parse_json(path.read_text())

    def schema(self):
        with tempfile.TemporaryDirectory(prefix="canister-schema-") as work:
            path = Path(work) / "schema.json"
            self.runner.run(Command("arcconf", ("GETCONFIGJSON", "SCHEMA", str(path), "nologs")))
            return parse_json(path.read_text())

    def list(self):
        return self.runner.run(Command("arcconf", ("LIST", "nologs")))

    def status(self, controller):
        if type(controller) is not int or controller < 1:
            raise ValueError("Positive controller index required")
        return self.runner.run(Command("arcconf", ("GETSTATUS", controller, "nologs")))
