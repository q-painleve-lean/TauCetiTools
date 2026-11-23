#!/usr/bin/env bash
# lake-cache-bundle.sh — carry the root package's own Lake outputs between CI runs in one
# GitHub Actions cache entry, with Lake's native staging. Enabled by
# `[services.cache] ci_bundle = true` (TAUCETI_CACHE_CI_BUNDLE=1); independent of any cache
# service, so a project with no public cache still reuses main's build.
#
# Usage: bash scripts/lake-cache-bundle.sh save    <project-dir> <bundle-dir>
#        bash scripts/lake-cache-bundle.sh restore <project-dir> <bundle-dir>
#
# save    Main CI only, after its build and audits. Packs the built outputs into the
#         local Lake cache (no recompile), emits the root package's input->output map and copies
#         exactly those records and archives to <bundle-dir> with `lake cache stage`. A bundle
#         larger than LAKE_BUNDLE_LIMIT_BYTES (default 256 MiB) is dropped with a warning, and the
#         step output saved=false tells the workflow not to upload it.
# restore PR, merge-queue, full-lint and main builds, and nightly-verify's reference build, before
#         any candidate code runs. Copies a bundle the workflow restored to <bundle-dir> back into
#         <project-dir>/.lake/cache with
#         `lake cache unstage`, drops any record whose archive did not arrive, and enables the
#         artifact cache for the offline build. Lake still compares every module's input hash, so
#         only unchanged modules restore; the rest build from source. No bundle, or a failed
#         unstage, leaves the build exactly as without this step.
#
# Main restores its newest bundle only while nightly verification runs (`[features] security_audit`).
# In place of a from-source build on every push, nightly-verify.yml rebuilds main from source once a
# day and compares the result with that commit's bundle (see ci.yml).
set -euo pipefail

ACTION="${1:?usage: lake-cache-bundle.sh save|restore <project-dir> <bundle-dir>}"
PROJECT_DIR="$(cd "${2:?project dir required}" && pwd)"
BUNDLE_DIR="${3:?bundle dir required}"
CACHE="$PROJECT_DIR/.lake/cache"
LIMIT="${LAKE_BUNDLE_LIMIT_BYTES:-268435456}"
case "$LIMIT" in ''|*[!0-9]*) echo "::error::LAKE_BUNDLE_LIMIT_BYTES must be a natural number"; exit 1 ;; esac

output() { echo "$1" >> "${GITHUB_OUTPUT:-/dev/null}"; }

case "$ACTION" in
  save)
    output saved=false
    rm -rf "$BUNDLE_DIR"
    (
      cd "$PROJECT_DIR"
      # Never download here: only the outputs this build produced belong in the bundle.
      export LAKE_ARTIFACT_CACHE=true LAKE_RESTORE_ARTIFACTS=true LAKE_NO_CACHE=true LAKE_CACHE_DIR="$CACHE"
      lake build --rehash -o .lake/outputs.jsonl >/dev/null
      lake cache stage .lake/outputs.jsonl "$BUNDLE_DIR"
    )
    entries=$(($(wc -l < "$BUNDLE_DIR/outputs.jsonl") - 1))
    bytes=$(du -sb "$BUNDLE_DIR" | cut -f1)
    if [ "$bytes" -gt "$LIMIT" ]; then
      echo "::warning::CI bundle is $bytes bytes, over the $LIMIT-byte limit; not saving it"
      rm -rf "$BUNDLE_DIR"
      exit 0
    fi
    echo "CI bundle: $entries root-package records, $bytes bytes"
    output saved=true
    ;;
  restore)
    if [ ! -f "$BUNDLE_DIR/outputs.jsonl" ]; then
      echo "CI bundle: none restored; building the root package from source"
      exit 0
    fi
    if ! ( cd "$PROJECT_DIR" && LAKE_CACHE_DIR="$CACHE" lake cache unstage "$BUNDLE_DIR" ); then
      echo "::warning::lake cache unstage failed; building the root package from source"
      exit 0
    fi
    # An interrupted unstage could leave a record without its archive, which `--iofail` would
    # turn into a failure; dropping it makes that module an ordinary cache miss.
    python3 "$(dirname -- "${BASH_SOURCE[0]}")/lake_cache_prune.py" "$CACHE"
    echo "CI bundle: restored $(($(wc -l < "$BUNDLE_DIR/outputs.jsonl") - 1)) root-package records"
    {
      echo "LAKE_CACHE_DIR=$CACHE"
      echo "LAKE_ARTIFACT_CACHE=true"
      echo "LAKE_RESTORE_ARTIFACTS=true"
    } >> "${GITHUB_ENV:-/dev/null}"
    ;;
  *)
    echo "::error::unknown action $ACTION"; exit 1 ;;
esac
