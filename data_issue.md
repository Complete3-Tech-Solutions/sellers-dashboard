# Data issue: INVOICED / PMT RECD columns are stale template values

**Status:** Cash Position chart + Invoiced/Pmt Recd/A-R columns **hidden** in the
dashboard (2026-06-04). Not a code bug — a source-data problem. This documents
why, with evidence, and how to restore the feature if real billing data appears.

## TL;DR

The `INVOICED`, `PMT RECD`, and `OPEN PO` columns in the *Profit Summary* (`PS SCC`)
spreadsheets are **not maintained per project**. They carry leftover example values
copied forward each year from the prior workbook's template. The parser and the
dashboard chart are both correct; the underlying data is not. Any feature built on
those columns (Cash Position / Accounts Receivable) shows meaningless numbers, so
they've been hidden until a real billing source exists.

## Evidence

Reading the first two project rows of every workbook (2010–2026), columns
`OPEN PO[13]`, `INVOICED[14]`, `PMT RECD[16]`:

| Workbook (year) | row 1 job | openPO | invoiced | pmt recd |
|---|---|---|---|---|
| 2012 | 238 | 2225 | 120787.5 | 118780.5 |
| 2013 | 323 | 2225 | 120787.5 | 118780.5 |
| 2014 | 466 | 2225 | 120787.5 | 118780.5 |
| 2016 | 1041 | 2225 | 120787.5 | 118780.5 |
| 2018 | 1504 | 2225 | 120787.5 | 118780.5 |
| 2020 | 1686 | 2225 | 120787.5 | 118780.5 |
| 2022 | 2137 | 2225 | 120787.5 | 118780.5 |
| 2024 | 2588 | 2225 | 120787.5 | 118780.5 |
| 2025 | 2729 | 2225 | 120787.5 | 118780.5 |

The **same** `invoiced=120787.5 / pmt=118780.5` (and row 2's `43339 / 43339`)
appear for **completely different jobs every year, 2012→2025**. Real per-project
billing amounts cannot be identical across 13 years and dozens of unrelated jobs.
(2010 is blank; 2011 and 2015 carry a different ghost set, `241575 / 237561`.)
Most other rows in each sheet are blank; a few hold other values that are likely
also stale. Conclusion: these columns are template ghosts, not data.

Reproduce:

```bash
cd "Profit Summaries"
uv run --with openpyxl python3 - <<'PY'
import openpyxl, glob
for f in sorted(glob.glob("*.xlsx")):
    ws = openpyxl.load_workbook(f, data_only=True, read_only=True).worksheets[0]
    for r in ws.iter_rows(values_only=True):
        if r[1] and r[2] and r[1] != "JOB #":
            print(f, "| job", r[1], "| invoiced[14]", r[14], "| pmt[16]", r[16]); break
PY
```

## What is NOT the problem

- **Parser** ([backend/app/services/parser.py](backend/app/services/parser.py)) — column
  mapping (`invoiced = r[14]`, `pmt_recd = r[16]`) is **correct and identical across
  all 21 workbooks**. The `next.md` worry that "column positions may vary by year"
  does not hold for this dataset; positions are stable 2010–2026.
- **Dashboard chart** ([dashboard/index.html](dashboard/index.html) `renderCashChart`)
  — the math is correct: `unbilled = max(0, contract − invoiced)`,
  `A/R = max(0, invoiced − paid)`. No code bug.
- **`next.md`'s diagnosis** was half right: the DB nulls came from snapshots parsed
  before commit `a44050b` (which added these columns). But re-uploading would only
  replace nulls with the **ghost values above** — not real billing data. So
  re-uploading does not actually fix the Cash Position chart.

## What was changed (hidden, reversible)

All in [dashboard/index.html](dashboard/index.html), marked with `BILLING HIDDEN`:

1. **Cash Position card** — commented out; the row grid switched `grid-2 → grid-1`
   so the Scatter chart goes full-width.
2. **`renderCashChart(d)` call** — commented out (the function itself is kept).
3. **Project Register table** — `Invoiced`, `Pmt Recd`, `A/R` `<th>` commented out
   and the matching `<td>` cells removed (7 columns now, header/body in sync).
4. **PDF export** — same three columns dropped from `head`/`body`, their
   `columnStyles` (7/8/9), and the A/R cell-coloring rule removed.

Reliable fields are untouched: `Contract`, `Cost`, `Profit`, `% Compl`, `Margin`,
and the contract-based `Sales` KPI / quarterly charts all still render.

## How to restore

If the customer starts maintaining real invoicing/payment data (in these sheets or
elsewhere):

1. If the data lives in a **different** source, point the parser at it (the column
   mapping in `parse_project_list_blocks` is where `r[14]`/`r[16]` are read).
2. Reverse the four edits above (search `BILLING HIDDEN` in `index.html`): uncomment
   the Cash Position card, restore `grid-2`, re-enable `renderCashChart(d)`, restore
   the three table `<th>`/`<td>` and the PDF columns/styles.
3. Re-upload the affected fiscal years through the agent so the DB picks up the new
   values.

## Recommendation

Confirm with the customer whether they track invoicing/AR anywhere. If not, leave
this hidden — showing ghost billing numbers is worse than omitting the feature.
