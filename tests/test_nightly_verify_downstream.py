"""Nightly verification gets its shared tools in a downstream.

`[features] security_audit` installs nightly-verify.yml in any project, but the workflow calls
shared scripts (lint-env.sh, lake-cache-get.sh, compare-build-outputs.py, the bundled bubblewrap)
from the checkout. Tau Ceti keeps them in its repository; a downstream gets them only from the
setup step, which rendering attaches to unpathed and `gate` checkouts and so skipped nightly's
`fresh` and `reference` checkouts of main. A downstream's nightly now gets one setup step after
each, pointed at that checkout; Tau Ceti's rendering is unchanged.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from tauceti_tools.project import load
from tauceti_tools.scaffold import initial_configuration
from tauceti_tools.templates import write_project


def render(repo: str) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        config = root / "tauceti.toml"
        text = initial_configuration(repo, "human").replace("security_audit = false", "security_audit = true")
        config.write_text(
            text
            + '\n[tools.tools]\nrepo="TauCetiProject/TauCetiTools"\nref="' + "a" * 40
            + '"\n[tools.review]\nrepo="TauCetiProject/TauCetiReview"\nref="' + "b" * 40 + '"\n'
        )
        write_project(load(str(config)), root)
        return yaml.safe_load((root / ".github/workflows/nightly-verify.yml").read_text())


def setups(steps: list[dict]) -> list[tuple[int, str]]:
    return [
        (i, step["with"]["project-directory"])
        for i, step in enumerate(steps)
        if step.get("name") == "Prepare pinned shared tools"
    ]


class NightlyVerifySetup(unittest.TestCase):
    def test_downstream_prepares_both_checkouts_of_main(self):
        steps = render("one/Project")["jobs"]["verify"]["steps"]
        checkouts = {step["with"]["path"]: i for i, step in enumerate(steps)
                     if step.get("uses", "").startswith("actions/checkout@")}
        self.assertEqual(set(checkouts), {"fresh", "reference"})
        self.assertEqual(setups(steps), [(checkouts["fresh"] + 1, "fresh"), (checkouts["reference"] + 1, "reference")])
        for i, step in enumerate(steps):
            run = step.get("run", "")
            if "scripts/" in run or "tauceti-shared-scripts" in run:
                with self.subTest(step=step.get("name")):
                    self.assertGreater(i, checkouts["reference"] + 1)
        for _, step in ((i, steps[i]) for i, _ in setups(steps)):
            self.assertEqual(step["with"]["source-mirror-enabled"], False)

    def test_tau_ceti_keeps_its_own_scripts(self):
        steps = render("TauCetiProject/TauCeti")["jobs"]["verify"]["steps"]
        self.assertEqual(setups(steps), [])


if __name__ == "__main__":
    unittest.main()
