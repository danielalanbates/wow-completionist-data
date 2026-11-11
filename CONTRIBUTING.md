# Contributing

Thank you for helping. Most fixes are one small JSON entry in `corrections/`.

## Fix the wiki first when you can

The Warcraft Wiki is this dataset's source. If a quest page names the wrong giver, misses a `{{co}}` coordinate or
lists the wrong `previous` quest, editing the page fixes it for every client and every project at the next export.
Use `corrections/` for what the wiki cannot express, for client-specific positions (a Classic-only location on a
retail-first page), or while a wiki edit is waiting.

## A correction

Add an entry to any `corrections/<something>.json` file (create one per topic, e.g. `corrections/era-duskwood.json`).
The build applies every file in name order, entries in file order, after all generated data.
`corrections/_example.json` is a template (files starting with `_` are never applied).

```json
{
 "corrections": [
  {
   "id": "era-quest-5-start-coords",
   "flavor": "era",
   "kind": "quest",
   "key": 5,
   "op": "set",
   "path": "/start/0/coords",
   "value": [{"map": 1431, "x": 18.0, "y": 56.0}],
   "reason": "The wiki NPC page has no coordinates for this quest giver.",
   "evidence": "Checked in game on Classic Era 1.15.x with /way; screenshot in the pull request."
  }
 ]
}
```

| Field | Meaning |
|---|---|
| `id` | Unique name for the correction. Suggested: `<client>-<kind>-<key>-<what>`. |
| `flavor` | `era`, `tbc`, `mop`, `retail`, `forever`, or `all` (applies wherever the record exists, skips the rest). |
| `kind` | `quest`, `npc`, `object`, `achievement` or `mission`. |
| `key` | The record's id (quests, achievements, missions) or its `key` (npcs and objects: the wiki page title). |
| `op` | `set` (replace a value or create an object member), `add` (insert into a list at an index, or `-` to append; or add an object member), `remove`. |
| `path` | A [JSON Pointer](https://www.rfc-editor.org/rfc/rfc6901) into the record, e.g. `/end/0/coords`, `/prerequisites/breadcrumb/-`, `/min_level`. An empty path with `add` adds a whole new record (`value` is the record); with `remove` it deletes the record. |
| `value` | The new value (`set` and `add`). |
| `reason` | Why. Required. |
| `evidence` | How you know: client and version you checked in game, a wiki revision link, a screenshot in the PR. Expected; validation warns without it. |

What the build does for you: a correction that sets a `.../coords` list also sets that object's `coord_source` to
`{"type": "correction", "correction": "<id>"}` and `exact_version` to `true`; every corrected record lists the
correction ids it received in `corrections`.

### Common fixes

* **Move a quest giver / ender:** `set` `/start/0/coords` or `/end/0/coords` to `[{"map": <uiMapID>, "x": .., "y": ..}]`.
  `x`/`y` are 0-100 on that client's map (what `/way` and most map addons show). `map` must be a uiMapID listed in
  `data/<client>/maps.json`.
* **Locate an objective:** `set` `/objectives/<n>/coords` (n is the list position, starting at 0).
* **Prerequisites:** `set` `/prerequisites/required` to a list of groups, e.g. `[[123], [456, 789]]` = 123, and one
  of 456 / 789. `add` `/prerequisites/breadcrumb/-` with a quest id for a breadcrumb. Every id must be a quest of
  the same client.
* **A quest that is not in a client:** `remove` with an empty path.
* **An NPC's spawn points:** `set` `/coords` on the `npc` record (points need `exact_version` and `via`).

Look up a record's current content in its bucket file (`data/<client>/quests/<id range>.json`) or in
`build/completionist.sqlite` after `python3 tools/build_db.py build`.

## Before you open the pull request

```
python3 tools/validate.py                   # must end with "0 errors"
python3 -m unittest discover -s tests
python3 tools/privacy_check.py
```

## What we cannot accept

* Data copied from other databases or addons, or from sites without an open licence, even one value at a time.
  That includes emulator world databases (GPL), other quest addons' databases and commercial or non-commercial
  guide sites. Their licences do not allow mixing into a CC BY-SA dataset; see [docs/SOURCES.md](docs/SOURCES.md).
  What you saw in the game yourself, or what the Warcraft Wiki says, is fine.
* Personal data: no character, account or guild names, no e-mail addresses.

## Licence of contributions

By opening a pull request you agree that your data changes are licensed CC BY-SA 4.0 (see
[LICENSE-DATA](LICENSE-DATA)) and your code changes under the repository's code licence ([LICENSE](LICENSE)).

## Code changes

Standard library only (Python 3.9+). Output must stay deterministic: the same inputs must give byte-identical
`data/` files. Add a test in `tests/` for new behaviour. Questions: help@batesai.org.
