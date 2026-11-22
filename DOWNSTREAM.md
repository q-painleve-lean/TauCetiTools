# q-painleve-lean downstream branch

`downstream` is upstream `TauCetiProject/TauCetiTools` `main` plus the changes below, used by
`q-painleve-lean/QPainleve` (`[tools.tools]` in its `tauceti.toml`). `main` of this fork mirrors
upstream and carries nothing of its own.

Each change is one commit with a test. Remove a change once upstream carries the same fix.

| Change | Why | Files | Remove when |
| --- | --- | --- | --- |
| Keep the canonical bump-guard sentinel when rendering downstreams | Rendering rewrote the `TauCetiProject/TauCeti` literal in `check-bump.sh`, so a downstream ran Tau Ceti's Mathlib-only check and rejected every TauCeti bump | `tauceti_tools/assets/scripts/check-bump.sh`, `tests/test_upstreams.py` | upstream `check-bump.sh` no longer compares against a renderable literal |

## Taking a new upstream

```sh
git fetch upstream main
git switch downstream
git merge upstream/main          # never rebase or force-push downstream
uv run --python 3.12 python -m unittest tests.test_upstreams
git push origin downstream
```

Then, in QPainleve, regenerate the workflows at the new `downstream` commit:

```sh
tauceti-tools doctor --conf tauceti.toml --fix workflows --apply
```

and merge the resulting PR as an administrator (it changes human-owned files).
