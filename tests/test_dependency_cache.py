"""dependency-cache-get.py: pinned upstream packages' outputs from their own public Lake caches.

The properties that matter:

* each `[[upstreams]]` entry with cache endpoints is asked, through lake-cache-get.sh, for exactly
  the revision lake-manifest.json pins, as that package and repository;
* a hit enables the artifact cache for the offline build; a miss leaves it disabled;
* entries without endpoints, or whose manifest source or revision does not match, are not fetched;
* pr-build runs the step before the offline build, outside the root package's own cache gate.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from tauceti_tools.project import parse
from tauceti_tools.scaffold import initial_configuration
from tauceti_tools.templates import materialize

ROOT = Path(__file__).resolve().parents[1]
REV = "0123456789abcdef0123456789abcdef01234567"
UPSTREAM = {"repo": "dep/Upstream", "package": "Upstream", "cache_artifact_url": "https://cache.example/artifacts",
            "cache_revision_url": "https://cache.example/revisions"}

# A stand-in `lake`: records its argv and the service config; `--rev=<sha>` hits only for $FAKE_PUBLISHED.
FAKE_LAKE = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LAKE_ARGV"
cat "$LAKE_CONFIG" >> "$FAKE_LAKE_CONFIG"
case "${*: -1}" in
  --rev=*)
    rev="${*: -1}"; rev="${rev#--rev=}"
    [ "$rev" = "${FAKE_PUBLISHED:-}" ] && exit 0
    echo "error: outputs not found for revision $rev"; exit 1 ;;
  --max-revs=*)
    echo "error: no outputs found in 1 revisions from HEAD"; exit 1 ;;
esac
exit 2
"""


class DependencyCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        config = parse(initial_configuration("one/Project", "human").encode())
        materialize(config, self.root / "scripts")
        (self.root / "pr").mkdir()
        self.manifest({"name": "Upstream", "url": "https://github.com/dep/Upstream.git", "rev": REV})
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "lake").write_text(FAKE_LAKE)
        (bin_dir / "lake").chmod(0o755)
        (bin_dir / "sleep").write_text("#!/bin/sh\nexit 0\n")
        (bin_dir / "sleep").chmod(0o755)
        self.env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", RUNNER_TEMP=str(self.root),
                        FAKE_LAKE_ARGV=str(self.root / "argv"), FAKE_LAKE_CONFIG=str(self.root / "config"),
                        GITHUB_ENV=str(self.root / "env"))
        for name in ("LAKE_CACHE_BASE_REV", "LAKE_CACHE_MAX_REVS", "LAKE_CACHE_PACKAGE", "TAUCETI_CACHE_REPOSITORY"):
            self.env.pop(name, None)

    def tearDown(self):
        self._tmp.cleanup()

    def manifest(self, *packages):
        (self.root / "pr/lake-manifest.json").write_text(json.dumps({"packages": list(packages)}))

    def run_get(self, upstreams, **env):
        result = subprocess.run(["python3", str(self.root / "scripts/dependency-cache-get.py"), "pr"],
                                cwd=self.root, env=dict(self.env, TAUCETI_UPSTREAMS=json.dumps(upstreams), **env),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        read = lambda name: (self.root / name).read_text() if (self.root / name).exists() else ""
        return result.stdout, read("argv").splitlines(), read("env"), read("config")

    def test_hit_fetches_the_pinned_revision_and_enables_the_cache(self):
        out, argv, github_env, config = self.run_get([UPSTREAM], FAKE_PUBLISHED=REV)
        self.assertEqual(argv, [f"cache get --service tauceti-public --repo dep/Upstream --package=Upstream --rev={REV}"])
        self.assertIn('artifactEndpoint = "https://cache.example/artifacts"', config)
        self.assertIn('revisionEndpoint = "https://cache.example/revisions"', config)
        cache = (self.root / "pr/.lake/cache").resolve()
        self.assertEqual(github_env.splitlines(),
                         [f"LAKE_CACHE_DIR={cache}", "LAKE_ARTIFACT_CACHE=true", "LAKE_RESTORE_ARTIFACTS=true"])

    def test_miss_leaves_the_cache_disabled(self):
        out, argv, github_env, _ = self.run_get([UPSTREAM])
        self.assertTrue(argv)
        self.assertIn("LAKE_ARTIFACT_CACHE=false", github_env)
        self.assertNotIn("LAKE_ARTIFACT_CACHE=true", github_env)

    def test_upstreams_without_cache_endpoints_are_not_fetched(self):
        out, argv, github_env, _ = self.run_get([{"repo": "dep/Upstream", "package": "Upstream"}])
        self.assertEqual((argv, github_env), ([], ""))

    def test_mismatched_manifest_or_endpoint_is_not_fetched(self):
        for upstream, package in (
            (UPSTREAM, {"name": "Upstream", "url": "https://github.com/other/Upstream", "rev": REV}),
            (UPSTREAM, {"name": "Upstream", "url": "https://github.com/dep/Upstream", "rev": "main"}),
            ({**UPSTREAM, "cache_artifact_url": "http://cache.example/artifacts"},
             {"name": "Upstream", "url": "https://github.com/dep/Upstream", "rev": REV}),
            ({**UPSTREAM, "cache_revision_url": 'https://cache.example/"x'},
             {"name": "Upstream", "url": "https://github.com/dep/Upstream", "rev": REV}),
        ):
            with self.subTest(upstream=upstream, package=package):
                self.manifest(package)
                out, argv, github_env, _ = self.run_get([upstream], FAKE_PUBLISHED=REV)
                self.assertEqual((argv, github_env), ([], ""))
                self.assertIn("not fetching its cache", out)

    def test_pr_build_fetches_dependencies_before_the_offline_build(self):
        steps = yaml.safe_load((ROOT / ".github/workflows/pr-build.yml").read_text())["jobs"]["sandboxed-build"]["steps"]
        runs = [step.get("run", "") for step in steps]
        fetch = next(i for i, run in enumerate(runs) if "dependency-cache-get.py pr" in run)
        build = next(i for i, step in enumerate(steps) if step.get("env", {}).get("SANDBOX_PHASE") == "build")
        self.assertLess(fetch, build)
        condition = steps[fetch]["if"]
        self.assertIn("env.INFRA != '1'", condition)
        self.assertNotIn("TAUCETI_CACHE_ENABLED", condition)


if __name__ == "__main__":
    unittest.main()
