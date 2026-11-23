"""A downstream's own merge sweep can hand recovery to its workers.

The sweep posts "Merge-queue recovery" requests as the project's App. Workers act only on
requests from trusted logins; the contract lists Tau Ceti's automation, and a downstream adds its
own App's login through TAUCETI_REBASE_AUTHORS in the worker configuration.
"""

import os
import unittest
from unittest.mock import patch

from tauceti_tools.survey_facts import rebase_authors, rebase_heads

HEAD = "a" * 40
BODY = f"Merge-queue recovery for head `{HEAD[:7]}`: conflicts with `main`.\n\n<!--tauceti-rebase:v1 {HEAD}-->"


def comment(login):
    return {"user": {"login": login}, "body": BODY}


class RebaseAuthors(unittest.TestCase):
    def test_contract_authors_are_trusted_without_configuration(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TAUCETI_REBASE_AUTHORS", None)
            self.assertEqual(rebase_heads([comment("tauceti-review-bot[bot]")]), [HEAD])
            self.assertEqual(rebase_heads([comment("example-automation[bot]")]), [])

    def test_configured_downstream_app_is_trusted(self):
        with patch.dict(os.environ, {"TAUCETI_REBASE_AUTHORS": " example-automation[bot] , other[bot]"}):
            self.assertIn("example-automation[bot]", rebase_authors())
            self.assertIn("tauceti-review-bot[bot]", rebase_authors())
            self.assertEqual(rebase_heads([comment("example-automation[bot]")]), [HEAD])
            self.assertEqual(rebase_heads([comment("someone-else")]), [])


if __name__ == "__main__":
    unittest.main()
