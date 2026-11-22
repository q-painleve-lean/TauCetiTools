"""Project workflow templates call only shared scripts that exist.

Upstream #227 removed lake_cache_reuse.py, but the downstream ci.yml, lint-full.yml and
publish-lake-cache.yml templates still called it, so every downstream's post-merge CI and daily
full lint failed before building. Downstream workflows run `scripts/<name>` from the materialized
shared scripts (tauceti_tools/assets/scripts) or the project's own compatibility entrypoints.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "tauceti_tools/assets"
WORKFLOWS = ASSETS / "project/.github/workflows"
REFERENCE = re.compile(r"(?:^|[\s\"'(/])scripts/([A-Za-z0-9_.-]+\.(?:py|sh))\b")
SPARSE = re.compile(r"tauceti_tools/assets/scripts/([A-Za-z0-9_.-]+\.(?:py|sh))\b")


class ProjectWorkflowScripts(unittest.TestCase):
    def available(self):
        return {path.name for directory in (ASSETS / "scripts", ASSETS / "project/scripts")
                for path in directory.iterdir() if path.is_file()}

    def test_every_called_script_exists(self):
        available = self.available()

        def code(workflow):
            # Comments may name scripts of other repositories (Tau Ceti's own scripts/).
            return "\n".join(line for line in workflow.read_text().splitlines()
                             if not line.lstrip().startswith("#"))

        missing = sorted({(workflow.name, name)
                          for workflow in WORKFLOWS.glob("*.yml")
                          for pattern in (REFERENCE, SPARSE)
                          for name in pattern.findall(code(workflow))
                          if name not in available})
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
