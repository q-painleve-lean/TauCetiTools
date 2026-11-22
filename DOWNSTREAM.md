# q-painleve-lean downstream branch

`downstream` is upstream `TauCetiProject/TauCetiTools` `main` plus the changes below, used by
`q-painleve-lean/QPainleve` (`[tools.tools]` in its `tauceti.toml`). `main` of this fork mirrors
upstream and carries nothing of its own.

Each change is one commit with a test. Remove a change once upstream carries the same fix.

| Change | Why | Files | Remove when |
| --- | --- | --- | --- |
| Keep the canonical bump-guard sentinel when rendering downstreams | Rendering rewrote the `TauCetiProject/TauCeti` literal in `check-bump.sh`, so a downstream ran Tau Ceti's Mathlib-only check and rejected every TauCeti bump | `tauceti_tools/assets/scripts/check-bump.sh`, `tests/test_upstreams.py` | upstream `check-bump.sh` no longer compares against a renderable literal |
| Render Tau Ceti's CI data service only for Tau Ceti | `ci_live_progress.py` posted every downstream build's progress, with a job OIDC token, to `ci-data.taucetiproject.org`, and its reporter thread made the finish step crash at exit (139/134) after every check had passed, ejecting PRs from the merge queue. Other projects now render the URL empty, and the reporter then execs the launcher | `tauceti_tools/templates.py` (`ci_data_url`), `tauceti_tools/assets/scripts/ci_live_progress.py`, `tests/test_live_progress.py` | upstream renders `ci-data.taucetiproject.org` per project, or the reporter no longer contacts it from other projects |
| Fetch pinned upstream packages' outputs from their own Lake caches | Upstream fetches only the root package's outputs, so a project that requires TauCeti compiled all of TauCeti (about 780 modules) on every PR and merge-queue build. For each `[[upstreams]]` entry with `cache_artifact_url` and `cache_revision_url`, pr-build now asks that cache, through `lake-cache-get.sh`, for the revision `lake-manifest.json` pins | `tauceti_tools/assets/scripts/dependency-cache-get.py`, `tauceti_tools/assets/scripts/lake-cache-get.sh` (`LAKE_CACHE_PACKAGE`), `.github/workflows/pr-build.yml`, `tests/test_dependency_cache.py` | upstream restores dependency packages' outputs from their caches |
| Retry a dependency's cache patiently and keep what arrived | TauCeti's public cache sits behind bot protection that refuses part of a burst of about 28,000 downloads (403, "Just a moment..."). With three attempts 2 s apart and discard-on-incomplete, one refused artifact threw the whole cache away and the build compiled all of TauCeti (27 min), holding the merge queue. `lake-cache-get.sh` gains `LAKE_CACHE_ATTEMPTS`, `LAKE_CACHE_RETRY_DELAY`, `LAKE_CACHE_RETRY_GROWTH`, `LAKE_CACHE_RETRY_MAX_DELAY` and `LAKE_CACHE_INCOMPLETE=prune` (unset: unchanged); the dependency fetch uses 8 attempts 30, 60, then 120 s apart (about 12 min), then keeps every verified artifact and drops only the mappings whose artifacts are missing | `tauceti_tools/assets/scripts/lake-cache-get.sh`, `tauceti_tools/assets/scripts/lake_cache_prune.py`, `tauceti_tools/assets/scripts/dependency-cache-get.py`, `tests/test_dependency_cache.py` | upstream restores dependency caches with its own retry and partial-cache handling |
| Stop calling the removed `lake_cache_reuse.py` from project workflows | Upstream #227 (5d49641) removed `lake_cache_reuse.py` and moved pr-build to Lake's native `lake cache stage`, but the downstream `ci.yml`, `lint-full.yml` and `publish-lake-cache.yml` templates still called it, so every downstream's post-merge CI and daily full lint failed before building. The templates now drop the snapshot step and stage with `lake build --rehash -o` and `lake cache stage`, as pr-build does; a test checks that every script a project workflow calls exists | `tauceti_tools/assets/project/.github/workflows/ci.yml`, `lint-full.yml`, `publish-lake-cache.yml`, `tests/test_project_workflow_scripts.py` | upstream's project workflow templates no longer reference `lake_cache_reuse.py` |

## Taking a new upstream

Merge often; each change above is small so that merges stay clean.

```sh
git fetch upstream main
git switch downstream
git merge upstream/main          # never rebase or force-push downstream
uv run --python 3.12 --extra test python -m unittest tests.test_upstreams tests.test_live_progress tests.test_dependency_cache
git push origin downstream
```

On a conflict in a listed file, take upstream's version and reapply that change. Check each
"Remove when" condition after the merge and drop changes upstream now covers.

Then, in QPainleve, regenerate the workflows at the new `downstream` commit:

```sh
tauceti-tools doctor --conf tauceti.toml --fix workflows --apply
```

and merge the resulting PR as an administrator (it changes human-owned files).
