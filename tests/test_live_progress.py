"""Trusted reporter isolation and its actual bounded-reader/exit-status regressions."""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from tauceti_tools.project import load
from tauceti_tools.scaffold import initial_configuration
from tauceti_tools.templates import CI_DATA_URL, ci_data_url, render

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "tauceti_tools/assets/scripts/test_ci_live_progress.py"
spec = importlib.util.spec_from_file_location("progress_regressions", ASSET)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Progress = module.Progress


class WorkflowIsolation(unittest.TestCase):
    def test_reporter_wraps_the_existing_clean_environment_and_sandbox(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/pr-build.yml").read_text())
        job = workflow["jobs"]["sandboxed-build"]
        self.assertEqual(job["permissions"]["id-token"], "write")
        caller = yaml.safe_load((ROOT / "tauceti_tools/assets/project/.github/workflows/pr-build.yml").read_text())
        self.assertEqual(caller["permissions"]["id-token"], "write")
        phases = [s for s in job["steps"] if "SANDBOX_PHASE" in s.get("env", {})]
        self.assertEqual(len(phases), 6)
        for step in phases:
            build = step["run"]
            self.assertIn('"${progress_observer[@]}" "${resource_observer[@]}" env -i /usr/bin/bwrap', build)
            self.assertNotIn("--setenv ACTIONS_ID_TOKEN", build)
            self.assertIn("--unshare-pid --unshare-net", build)
            self.assertIn("--remount-ro /", build)

    def test_post_build_shim_probe_cannot_reach_the_job_oidc_or_host_processes(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/pr-build.yml").read_text())
        step = next(s for s in workflow["jobs"]["sandboxed-build"]["steps"] if s.get("id") == "shim_expiry")
        self.assertIn("env -i /usr/bin/bwrap --tmpfs /", step["run"])
        self.assertIn("--unshare-pid --unshare-net", step["run"])
        self.assertIn("--remount-ro /", step["run"])
        self.assertNotIn("--setenv ACTIONS_ID_TOKEN", step["run"])
        self.assertIn('"${probe_mounts[@]}"', step["run"])


class DownstreamReporting(unittest.TestCase):
    """Only Tau Ceti reports to its CI data service; another project runs the launcher directly."""

    def project(self, root, repo):
        config = Path(root) / repo.replace("/", "-") / "tauceti.toml"
        config.parent.mkdir()
        config.write_text(initial_configuration(repo, "human"))
        return load(str(config))

    def test_only_tau_ceti_renders_the_ci_data_service(self):
        source = (ROOT / "tauceti_tools/assets/scripts/ci_live_progress.py").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            downstream = self.project(tmp, "ExampleOrg/ExampleCeti")
            canonical = self.project(tmp, "TauCetiProject/TauCeti")
            self.assertEqual(ci_data_url(downstream), "")
            self.assertEqual(ci_data_url(canonical), CI_DATA_URL)
            self.assertIn('ORIGIN = ""\n', render(source, downstream))
            self.assertNotIn("taucetiproject.org", render(source, downstream))

    def test_downstream_reporter_becomes_the_launcher(self):
        source = (ROOT / "tauceti_tools/assets/scripts/ci_live_progress.py").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "ci_live_progress.py"
            script.write_text(render(source, self.project(tmp, "ExampleOrg/ExampleCeti")))
            # Token variables are present, as in pr-build: a reporter would try to use them.
            env = dict(os.environ, RUNNER_TEMP=tmp, ACTIONS_ID_TOKEN_REQUEST_TOKEN="unused",
                       ACTIONS_ID_TOKEN_REQUEST_URL="https://example.invalid/token?x=1")
            reporter = subprocess.Popen(
                [sys.executable, str(script), "--telemetry", tmp, "--", "sh", "-c", 'echo "$$"; exit 7'],
                env=env, stdout=subprocess.PIPE, text=True)
            output, _ = reporter.communicate(timeout=30)
            # The launcher replaced the reporter process and its exit status is the result.
            self.assertEqual(reporter.returncode, 7)
            self.assertEqual(output.strip(), str(reporter.pid))
            self.assertFalse((Path(tmp) / "ci-live-progress-session.json").exists())


if __name__ == "__main__":
    unittest.main()
