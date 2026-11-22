# q-painleve-lean downstream branch

`downstream` is upstream `TauCetiProject/TauCetiTools` `main` plus the changes below, used by
`q-painleve-lean/QPainleve` (`[tools.tools]` in its `tauceti.toml`). `main` of this fork mirrors
upstream and carries nothing of its own.

Each change is one commit with a test. Remove a change once upstream carries the same fix.

| Change | Why | Files | Remove when |
| --- | --- | --- | --- |
| Keep the canonical bump-guard sentinel when rendering downstreams | Rendering rewrote the `TauCetiProject/TauCeti` literal in `check-bump.sh`, so a downstream ran Tau Ceti's Mathlib-only check and rejected every TauCeti bump | `tauceti_tools/assets/scripts/check-bump.sh`, `tests/test_upstreams.py` | upstream `check-bump.sh` no longer compares against a renderable literal |
| Render Tau Ceti's CI data service only for Tau Ceti | `ci_live_progress.py` posted every downstream build's progress, with a job OIDC token, to `ci-data.taucetiproject.org`, and its reporter thread made the finish step crash at exit (139/134) after every check had passed, ejecting PRs from the merge queue. Other projects now render the URL empty, and the reporter then execs the launcher | `tauceti_tools/templates.py` (`ci_data_url`), `tauceti_tools/assets/scripts/ci_live_progress.py`, `tests/test_live_progress.py` | upstream renders `ci-data.taucetiproject.org` per project, or the reporter no longer contacts it from other projects |

## Taking a new upstream

Merge often; each change above is small so that merges stay clean.

```sh
git fetch upstream main
git switch downstream
git merge upstream/main          # never rebase or force-push downstream
uv run --python 3.12 --extra test python -m unittest tests.test_upstreams tests.test_live_progress
git push origin downstream
```

On a conflict in a listed file, take upstream's version and reapply that change. Check each
"Remove when" condition after the merge and drop changes upstream now covers.

Then, in QPainleve, regenerate the workflows at the new `downstream` commit:

```sh
tauceti-tools doctor --conf tauceti.toml --fix workflows --apply
```

and merge the resulting PR as an administrator (it changes human-owned files).
