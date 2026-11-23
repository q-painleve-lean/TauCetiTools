"""toolchain-tags.yml is installed only where it can report: in Tau Ceti, or with Zulip enabled.

The workflow's only output is a post to Zulip ("Toolchain tags"). `[features] security_audit` ships
it with nightly-verify.yml, so a downstream without Zulip that wants nightly verification also got
a workflow that can only fail, on every lean-toolchain change. Rendering now skips it there.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tauceti_tools.project import load
from tauceti_tools.scaffold import initial_configuration
from tauceti_tools.templates import write_project


def written(repo: str, *, zulip: bool) -> list[str]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        config = root / "tauceti.toml"
        text = initial_configuration(repo, "human").replace("security_audit = false", "security_audit = true")
        if zulip:
            text = text.replace("zulip = false", "zulip = true")
        config.write_text(
            text
            + '\n[tools.tools]\nrepo="TauCetiProject/TauCetiTools"\nref="' + "a" * 40
            + '"\n[tools.review]\nrepo="TauCetiProject/TauCetiReview"\nref="' + "b" * 40 + '"\n'
        )
        return write_project(load(str(config)), root)


class ToolchainTags(unittest.TestCase):
    def test_downstream_without_zulip_gets_nightly_but_not_toolchain_tags(self):
        files = written("one/Project", zulip=False)
        self.assertIn(".github/workflows/nightly-verify.yml", files)
        self.assertNotIn(".github/workflows/toolchain-tags.yml", files)

    def test_downstream_with_zulip_keeps_toolchain_tags(self):
        self.assertIn(".github/workflows/toolchain-tags.yml", written("one/Project", zulip=True))

    def test_tau_ceti_keeps_toolchain_tags(self):
        self.assertIn(".github/workflows/toolchain-tags.yml", written("TauCetiProject/TauCeti", zulip=False))


if __name__ == "__main__":
    unittest.main()
