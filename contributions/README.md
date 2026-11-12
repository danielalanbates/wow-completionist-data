# Player contributions

Where players actually stood when they accepted a quest, turned it in, made progress on an objective, or finished a
step. Collected by the Completionist's Guide addon's **Contribute** box, sent in by players, merged here.

| File | What it is |
|---|---|
| `raw/<contributor>.txt` | one file per contributor (a 12-digit hash, never a name), their newest submission |
| `spots/<flavor>.csv` | every grid cell: `key, map, x, y, weight, contributors` |
| `areas/<flavor>.json` | the most likely places per step: centre, radius, weight, contributors, confidence |
| `contributions.sqlite` | the same as SQL tables `spots`, `areas`, `contributors` |
| `trusted.txt` | hashes of maintainers; their areas are marked `trusted` |

`key` is `A:<quest id>` (accept), `T:<quest id>` (turn-in), `C:<quest id>:<objective>` (objective progress) or
`G:<guide id>#<step key>` (a step with no quest). `x`, `y` are map positions from 0 to 100.
`confidence` is `trusted`, `confirmed` (two or more contributors put it in the same place) or `single`.

## How to contribute

1. In the addon, tick **Contribute** on the step window and play.
2. Click the word **Contribute** (or type `/cr contribute export`), select all, copy.
3. Open a new issue here with the **Location contribution** form and paste the text. If it is long, save it as a
   `.txt` file and drag the file into the box instead.

A GitHub Action checks the text, merges it and closes the issue with a short report. Sending again replaces your
earlier contribution, so always send the full export.

What is in the text: a client flavor and build, quest ids or step keys, map ids, positions and weights. No character,
realm or account names and no times. One contributor counts at most 3 per grid cell.

## Example queries

```sql
-- the most likely place to accept quest 179 on Classic Era
select map, x, y, r, weight, contributors, confidence
from areas where flavor = 'era' and key = 'A:179' order by rank;

-- objectives seen in more than one place
select key, count(*) from areas where flavor = 'retail' and key like 'C:%' group by key having count(*) > 1;
```

Licence: CC BY-SA 4.0, like the rest of the data (see `LICENSE-DATA`). By sending a contribution you agree to publish it under that licence
and confirm that you recorded the positions yourself by playing. Tool: `tools/contrib.py`.
