#!/usr/bin/env python3
"""Restore pinned upstream packages' outputs from their own public Lake caches.

A project that requires another Lake package with a public cache would otherwise compile that
whole package from source on every build. An `[[upstreams]]` entry in tauceti.toml that sets
both `cache_artifact_url` and `cache_revision_url` names that cache. For each such upstream this
asks the cache for the outputs of exactly the revision lake-manifest.json pins, through
lake-cache-get.sh, so retries, partial-transfer handling and the no-cache fallback are the same
as for the root package's own cache.

Usage: python3 scripts/dependency-cache-get.py <project-dir>

The endpoints come only from the trusted project configuration (TAUCETI_UPSTREAMS), never from
the candidate. The candidate's manifest supplies only the revision, and only for a package whose
source is that upstream's repository. Anonymous reads; no token, no PR code. A miss is not
fatal: the build compiles the package from source as it does without this step. A fetch that
stays incomplete after the retries keeps every verified artifact and drops only the mappings whose
artifacts are missing, so only those modules build from source.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

SHA = re.compile(r"[0-9a-f]{40}")
GET = Path(__file__).resolve().with_name("lake-cache-get.sh")
DISABLE = ("LAKE_ARTIFACT_CACHE=false", "LAKE_RESTORE_ARTIFACTS=false", "LAKE_CACHE_DIR=")
RETRY = {"LAKE_CACHE_ATTEMPTS": "8", "LAKE_CACHE_RETRY_DELAY": "30", "LAKE_CACHE_RETRY_GROWTH": "2",
         "LAKE_CACHE_RETRY_MAX_DELAY": "120", "LAKE_CACHE_INCOMPLETE": "prune"}


def endpoint(value):
    """A plain anonymous HTTPS URL, safe to write into Lake's TOML service config."""
    url = urlsplit(value) if isinstance(value, str) else None
    if (url is None or url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or re.search(r'[\s"\\]', value)):
        raise ValueError("cache endpoints must be plain HTTPS URLs")
    return value.rstrip("/")


def dependencies(upstreams, manifest):
    """Yield (package, repo, rev, artifacts, revisions) for each configured upstream cache."""
    packages = {p.get("name"): p for p in manifest.get("packages", []) if isinstance(p, dict)}
    for upstream in upstreams:
        if not isinstance(upstream, dict):
            continue
        if not (upstream.get("cache_artifact_url") or upstream.get("cache_revision_url")):
            continue
        name, repo = upstream.get("package"), upstream.get("repo")
        try:
            artifacts = endpoint(upstream.get("cache_artifact_url"))
            revisions = endpoint(upstream.get("cache_revision_url"))
        except ValueError as error:
            print(f"::warning::{name}: {error}; not fetching its cache")
            continue
        package = packages.get(name)
        if package is None:
            print(f"::warning::{name}: not in lake-manifest.json; not fetching its cache")
            continue
        if str(package.get("url", "")).removesuffix(".git") != f"https://github.com/{repo}":
            print(f"::warning::{name}: lake-manifest.json source is not {repo}; not fetching its cache")
            continue
        rev = package.get("rev")
        if not isinstance(rev, str) or not SHA.fullmatch(rev):
            print(f"::warning::{name}: lake-manifest.json pins no full commit SHA; not fetching its cache")
            continue
        yield name, repo, rev, artifacts, revisions


def append_env(lines):
    path = os.environ.get("GITHUB_ENV")
    if path:
        with open(path, "a") as output:
            output.write("".join(line + "\n" for line in lines))


def main(project: Path) -> None:
    project = project.resolve()
    upstreams = json.loads(os.environ.get("TAUCETI_UPSTREAMS") or "[]")
    manifest = json.loads((project / "lake-manifest.json").read_text())
    cache = project / ".lake/cache"
    fetched = False
    for name, repo, rev, artifacts, revisions in dependencies(upstreams, manifest):
        print(f"Fetching {name}'s outputs for {rev} from its public Lake cache", flush=True)
        with tempfile.TemporaryDirectory(prefix="dependency-cache-") as temporary:
            github_env = Path(temporary) / "env"
            env = dict(os.environ, PUBLIC_ARTIFACT_ENDPOINT=artifacts, PUBLIC_REVISION_ENDPOINT=revisions,
                       TAUCETI_CACHE_REPOSITORY=repo, LAKE_CACHE_PACKAGE=name, LAKE_CACHE_BASE_REV=rev,
                       LAKE_CACHE_MAX_REVS="1", LAKE_CACHE_DIR=str(cache), GITHUB_ENV=str(github_env),
                       # A public cache behind bot protection refuses bursts for a while. Keep every
                       # verified artifact across eight attempts 30 s, 60 s, then 120 s apart (about 12 min), and if
                       # some still never arrive, build only those modules rather than the whole
                       # package (lake-cache-get.sh, LAKE_CACHE_INCOMPLETE=prune).
                       **RETRY)
            try:
                subprocess.run(["bash", str(GET), str(project)], env=env, check=True)
            except (OSError, subprocess.CalledProcessError) as error:
                print(f"::warning::{name}: dependency cache fetch failed ({error}); building without the cache")
                append_env(DISABLE)
                return
            unclean = github_env.exists() and "LAKE_ARTIFACT_CACHE=false" in github_env.read_text()
        if unclean:
            # lake-cache-get.sh has already discarded the whole cache: build with none.
            append_env(DISABLE)
            return
        fetched = True
    if fetched:
        append_env((f"LAKE_CACHE_DIR={cache}", "LAKE_ARTIFACT_CACHE=true", "LAKE_RESTORE_ARTIFACTS=true"))


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
