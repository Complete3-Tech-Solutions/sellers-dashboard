It's a data issue, not a logic issue.

The chart code in dashboard/index.html:846-861 is correct — the math is right. The problem is that invoiced and pmt_recd are null/0 for all projects in the DB, so:

totalPaid = 0 → Cash Received segment = 0
outstanding = max(0, 0 - 0) = 0 → A/R segment = 0
unbilled = max(0, totalContract - 0) = totalContract → entire contract value shows as Unbilled Backlog
Why the data is missing — there are two layers:

Parser reads hardcoded columns (parser.py:274-275): invoiced = r[14], pmt_recd = r[16]. This was only added in commit a44050b (May 21). Any snapshot uploaded before that commit was processed without those columns, so the DB has all nulls. Re-uploading/re-processing the snapshot will fix it.

Column positions may vary by year: r[14] and r[16] were verified against the 2014 workbook. If other years have a different column layout, those files will still produce nulls even after a re-parse.

Quick check: Open the browser console and run:


DATA[currentYear].projects.filter(p => p.invoiced > 0).length
If it returns 0, the DB data has no billing values → re-upload your snapshot. If it returns non-zero but the chart still looks wrong, there's a different issue.