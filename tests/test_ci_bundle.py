"""CI bundle: main saves the root package's outputs once; PR, queue and full-lint builds restore them.

The properties that matter:

* `[services.cache] ci_bundle = true` alone turns it on (TAUCETI_CACHE_CI_BUNDLE=1); unset, nothing
  changes;
* save stages exactly the root map with `lake cache stage`, and refuses an oversized bundle;
* restore unstages with `lake cache unstage`, drops records whose archives are missing, enables the
  artifact cache, and is a no-op without a bundle;
* only main's build job saves, only a job that runs no project code may delete caches, and PR and
  full-lint builds restore after the dependency caches and before building;
* main restores its own newest bundle only together with nightly verification
  (`[features] security_audit`, TAUCETI_NIGHTLY_VERIFY=1), and nightly-verify compares its clean build
  with exactly the commit's bundle;
* every workflow names a bundle with the same key and path (actions/cache versions an entry by its
  path), so changing one alone cannot silently miss.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from tauceti_tools.project import load, parse
from tauceti_tools.scaffold import initial_configuration
from tauceti_tools.templates import materialize

ROOT = Path(__file__).resolve().parents[1]
PROJECT_WORKFLOWS = ROOT / "tauceti_tools/assets/project/.github/workflows"
KEPT, LOST = "c" * 16, "d" * 16

FAKE_LAKE = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LAKE_ARGV"
case "$1 $2" in
  "build --rehash")
    printf '"2026-03-17"\n["%s","%s.ltar"]\n["%s","%s.ltar"]\n' """ + f'"{KEPT}" "{KEPT}" "{LOST}" "{LOST}"' + r""" > .lake/outputs.jsonl ;;
  "cache stage")
    mkdir -p "$4/artifacts"; cp "$3" "$4/outputs.jsonl"
    head -c "${FAKE_ARTIFACT_BYTES:-10}" /dev/zero > "$4/artifacts/""" + KEPT + r""".ltar" ;;
  "cache unstage")
    mkdir -p "$LAKE_CACHE_DIR/outputs/One" "$LAKE_CACHE_DIR/artifacts"
    for h in """ + f"{KEPT} {LOST}" + r"""; do
      printf '{"schemaVersion":"2026-02-25","data":"%s.ltar"}' "$h" > "$LAKE_CACHE_DIR/outputs/One/$h.json"
    done
    cp "$3/artifacts/"*.ltar "$LAKE_CACHE_DIR/artifacts/" ;;
esac
"""


class Configuration(unittest.TestCase):
    def environment(self, extra):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "tauceti.toml"
            config.write_text(initial_configuration("one/Project", "human") + extra)
            return load(str(config)).environment()["TAUCETI_CACHE_CI_BUNDLE"]

    def test_ci_bundle_is_opt_in(self):
        self.assertEqual(self.environment(""), "")

    def test_ci_bundle_needs_no_cache_service(self):
        text = initial_configuration("one/Project", "human")
        self.assertIn("[services.cache]", text)
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "tauceti.toml"
            config.write_text(text.replace("[services.cache]\n", "[services.cache]\nci_bundle = true\n", 1))
            env = load(str(config)).environment()
        self.assertEqual(env["TAUCETI_CACHE_CI_BUNDLE"], "1")
        self.assertEqual(env["TAUCETI_CACHE_ARTIFACT_URL"], "")


class NightlyPairing(unittest.TestCase):
    def test_nightly_verify_follows_security_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "tauceti.toml"
            text = initial_configuration("one/Project", "human")
            config.write_text(text)
            self.assertEqual(load(str(config)).environment()["TAUCETI_NIGHTLY_VERIFY"], "")
            config.write_text(text.replace("security_audit = false", "security_audit = true"))
            self.assertEqual(load(str(config)).environment()["TAUCETI_NIGHTLY_VERIFY"], "1")


class Script(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        materialize(parse(initial_configuration("one/Project", "human").encode()), self.root / "scripts")
        (self.root / "project/.lake").mkdir(parents=True)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "lake").write_text(FAKE_LAKE)
        (bin_dir / "lake").chmod(0o755)
        self.env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", FAKE_LAKE_ARGV=str(self.root / "argv"),
                        GITHUB_ENV=str(self.root / "env"), GITHUB_OUTPUT=str(self.root / "output"))

    def tearDown(self):
        self._tmp.cleanup()

    def run_bundle(self, *args, **env):
        result = subprocess.run(["bash", str(self.root / "scripts/lake-cache-bundle.sh"), *args],
                                cwd=self.root, env=dict(self.env, **env), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        read = lambda name: (self.root / name).read_text() if (self.root / name).exists() else ""
        return result.stdout, read("argv").splitlines(), read("env"), read("output")

    def test_save_stages_the_root_map(self):
        out, argv, _, output = self.run_bundle("save", "project", str(self.root / "bundle"))
        self.assertEqual(argv, ["build --rehash -o .lake/outputs.jsonl",
                                f"cache stage .lake/outputs.jsonl {self.root / 'bundle'}"])
        self.assertTrue((self.root / "bundle/outputs.jsonl").exists())
        self.assertIn("2 root-package records", out)
        self.assertEqual(output.splitlines()[-1], "saved=true")

    def test_save_refuses_an_oversized_bundle(self):
        out, _, _, output = self.run_bundle("save", "project", str(self.root / "bundle"),
                                            FAKE_ARTIFACT_BYTES="5000", LAKE_BUNDLE_LIMIT_BYTES="1000")
        self.assertIn("not saving it", out)
        self.assertFalse((self.root / "bundle").exists())
        self.assertEqual(output.splitlines()[-1], "saved=false")

    def test_restore_without_a_bundle_changes_nothing(self):
        out, argv, env, _ = self.run_bundle("restore", "project", str(self.root / "absent"))
        self.assertEqual((argv, env), ([], ""))
        self.assertIn("none restored", out)

    def test_restore_unstages_prunes_and_enables_the_cache(self):
        self.run_bundle("save", "project", str(self.root / "bundle"))
        (self.root / "argv").unlink()
        out, argv, env, _ = self.run_bundle("restore", "project", str(self.root / "bundle"))
        self.assertEqual(argv, [f"cache unstage {self.root / 'bundle'}"])
        outputs = self.root / "project/.lake/cache/outputs/One"
        self.assertTrue((outputs / f"{KEPT}.json").exists())
        self.assertFalse((outputs / f"{LOST}.json").exists())
        cache = (self.root / "project/.lake/cache").resolve()
        self.assertEqual(env.splitlines(), [f"LAKE_CACHE_DIR={cache}", "LAKE_ARTIFACT_CACHE=true",
                                            "LAKE_RESTORE_ARTIFACTS=true"])


class Workflows(unittest.TestCase):
    def steps(self, path, job):
        return yaml.safe_load(path.read_text())["jobs"][job]["steps"]

    def index(self, steps, needle):
        return next(i for i, step in enumerate(steps) if needle in (step.get("run", "") + str(step.get("with", ""))))

    def test_pr_build_restores_after_dependencies_and_before_building(self):
        steps = self.steps(ROOT / ".github/workflows/pr-build.yml", "sandboxed-build")
        dependency = self.index(steps, "dependency-cache-get.py pr")
        restore = self.index(steps, "lake-bundle-v2-")
        install = self.index(steps, "lake-cache-bundle.sh restore pr")
        build = next(i for i, step in enumerate(steps) if step.get("env", {}).get("SANDBOX_PHASE") == "build")
        self.assertLess(dependency, restore)
        self.assertLess(restore, install)
        self.assertLess(install, build)
        self.assertIn("TAUCETI_CACHE_CI_BUNDLE == '1'", steps[restore]["if"])
        self.assertTrue(steps[restore]["uses"].startswith("actions/cache/restore@"))
        self.assertFalse(any("cache/save" in step.get("uses", "") and "lake-bundle" in str(step.get("with", ""))
                             for step in steps))

    def test_only_main_saves_and_only_a_code_free_job_deletes(self):
        workflow = yaml.safe_load((PROJECT_WORKFLOWS / "ci.yml").read_text())
        build = workflow["jobs"]["build"]
        steps = build["steps"]
        dependency = self.index(steps, "dependency-cache-get.py .")
        main_build = next(i for i, step in enumerate(steps) if step.get("name") == "Build")
        save = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("actions/cache/save@")
                    and "lake-bundle-v2-" in str(step.get("with", "")))
        self.assertLess(dependency, main_build)
        self.assertLess(main_build, save)
        self.assertTrue(steps[save]["uses"].startswith("actions/cache/save@"))
        self.assertNotIn("actions", build.get("permissions", workflow.get("permissions", {})))
        prune = workflow["jobs"]["prune-lake-bundles"]
        self.assertEqual(prune["permissions"], {"actions": "write"})
        self.assertEqual(prune["needs"], "build")
        self.assertFalse(any("uses" in step for step in prune["steps"]))
        self.assertIn("'.[3:][].id'", prune["steps"][0]["run"])

    def test_full_lint_restores_and_never_saves(self):
        steps = self.steps(PROJECT_WORKFLOWS / "lint-full.yml", "lint")
        restore = self.index(steps, "lake-bundle-v2-")
        build = next(i for i, step in enumerate(steps) if step.get("name") == "Build")
        self.assertLess(self.index(steps, "dependency-cache-get.py ."), restore)
        self.assertLess(restore, build)
        self.assertTrue(steps[restore]["uses"].startswith("actions/cache/restore@"))

    def test_main_restores_its_own_bundle_only_with_nightly_verification(self):
        steps = self.steps(PROJECT_WORKFLOWS / "ci.yml", "build")
        restore = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("actions/cache/restore@")
                       and "lake-bundle-v2-" in str(step.get("with", "")))
        install = self.index(steps, "lake-cache-bundle.sh restore .")
        main_build = next(i for i, step in enumerate(steps) if step.get("name") == "Build")
        self.assertLess(self.index(steps, "dependency-cache-get.py ."), restore)
        self.assertLess(restore, install)
        self.assertLess(install, main_build)
        condition = steps[restore]["if"]
        for term in ("TAUCETI_CACHE_CI_BUNDLE == '1'", "TAUCETI_NIGHTLY_VERIFY == '1'", "TAUCETI_CACHE_ENABLED != '1'"):
            self.assertIn(term, condition)
        self.assertIn("restore-keys", steps[restore]["with"])
        self.assertIn(steps[restore]["id"], steps[install]["if"])

    def test_nightly_compares_with_exactly_this_commits_bundle(self):
        steps = self.steps(PROJECT_WORKFLOWS / "nightly-verify.yml", "verify")
        names = [step.get("name") for step in steps]
        refcfg = names.index("Configure the Lake artifact cache for the reference build")
        fetch = names.index("Fetch main's CI bundle for this commit")
        restore = names.index("Restore what the cache serves for this commit")
        confirm = names.index("Confirm the reference workspace really restored from the cache")
        self.assertLess(refcfg, fetch)
        self.assertLess(fetch, restore)
        self.assertLess(restore, confirm)
        self.assertIn("source=bundle", steps[refcfg]["run"])
        self.assertIn('TAUCETI_CACHE_CI_BUNDLE:-}" = 1', steps[refcfg]["run"])
        fetched = steps[fetch]
        self.assertTrue(fetched["uses"].startswith("actions/cache/restore@"))
        self.assertNotIn("restore-keys", fetched["with"])
        self.assertTrue(fetched["with"]["key"].endswith("-${{ steps.rev.outputs.sha }}"))
        self.assertEqual(fetched["if"], "${{ steps.refcfg.outputs.source == 'bundle' }}")
        self.assertIn('lake-cache-bundle.sh restore reference "$RUNNER_TEMP/lake-bundle"', steps[restore]["run"])
        self.assertIn("lake-cache-get.sh reference", steps[restore]["run"])
        self.assertEqual(steps[restore]["id"], "restore")
        self.assertIn("steps.restore.outcome", steps[confirm]["run"])

    def test_every_workflow_names_a_bundle_the_same_way(self):
        expressions, paths = [], set()
        for path in (ROOT / ".github/workflows/pr-build.yml", *PROJECT_WORKFLOWS.glob("*.yml")):
            for job in yaml.safe_load(path.read_text())["jobs"].values():
                for step in job.get("steps", []):
                    if str(step.get("with", {}).get("key", "")).startswith("lake-bundle-v2-"):
                        # actions/cache derives an entry's version from its path, so a restore under
                        # another path never matches a saved bundle, whatever the key.
                        paths.add(step["with"]["path"])
                    for field in ("key", "restore-keys"):
                        value = str(step.get("with", {}).get(field, ""))
                        if value.startswith("lake-bundle-v2-"):
                            expressions.append((path.name, field, value))
        self.assertEqual(paths, {"${{ runner.temp }}/lake-bundle"})
        shapes = set()
        for name, field, value in expressions:
            shape = re.sub(r"hashFiles\('(?:[a-z]+/)?", "hashFiles('", value)
            shape = re.sub(r"\$\{\{ (?:github\.sha|steps\.rev\.outputs\.sha) \}\}$", "<sha>", shape)
            shapes.add(shape if field == "key" else shape + "<sha>")
        self.assertGreaterEqual(len(expressions), 7)
        self.assertEqual(len(shapes), 1, shapes)


if __name__ == "__main__":
    unittest.main()
