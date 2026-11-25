"""A repository name in backticks renders as that repository, not as the Lean root.

The `` `TauCeti `` key (a Lean name literal such as `` getRoot == `TauCeti ``) matched at the
backtick, one character before any repository key could, so `` `TauCetiProject/TauCeti `` rendered
as `` `ExampleCetiProject/ExampleCeti ``, a repository that does not exist. Worker prompts write
repository names in backticks.
"""

import unittest

from tauceti_tools.project import parse
from tauceti_tools.scaffold import initial_configuration
from tauceti_tools.templates import render


class BacktickRepositories(unittest.TestCase):
    def setUp(self):
        self.project = parse(initial_configuration("ExampleOrg/ExampleCeti", "human").encode())

    def test_backticked_repositories_render_as_the_project_repositories(self):
        roadmap = self.project.repos["roadmap"]
        source = (
            "Do not open a PR in `TauCetiProject/TauCetiRoadmap`.\n"
            "The PR is opened to `TauCetiProject/TauCeti:main`.\n"
            "Read `TauCetiRoadmap/` first.\n"
        )
        self.assertEqual(
            render(source, self.project),
            f"Do not open a PR in `{roadmap}`.\n"
            "The PR is opened to `ExampleOrg/ExampleCeti:main`.\n"
            f"Read `{self.project.roadmap_dir}/` first.\n",
        )

    def test_backticked_lean_names_still_render_as_the_root(self):
        source = "getRoot == `TauCeti) and `TauCeti.Foo` and `TauCeti/`\n"
        self.assertEqual(
            render(source, self.project),
            "getRoot == `ExampleCeti) and `ExampleCeti.Foo` and `ExampleCeti/`\n",
        )


if __name__ == "__main__":
    unittest.main()
