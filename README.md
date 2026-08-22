# Star Explorer

**Medicare Advantage Intelligence** — turn the entire CMS Medicare Advantage
universe into a ranked, signal-rich account list.

Star Explorer is a single-page web app that reads official CMS 2026 Star Ratings
and enrollment data and surfaces the plans that are losing stars, members, and
patience — scored by opportunity and sized by estimated contract value, so sales
teams can prioritize by revenue instead of digging through spreadsheets.

## Features

- **Landing page** — a focused, conversion-oriented intro to the tool.
- **Opportunity Scoring** — a 0–100 score fusing Star movement, member
  experience (CAHPS), and reachable contract value.
- **Live Signal Detection** — Star drops, language-access audit fails, complaint
  surges, disenrollment spikes, appeals risk.
- **Drill-Down Comparison** — any plan head-to-head against its market across all
  10 call-center measures, with an auto-selected North-Star benchmark.
- **Discovery Rows** — a browse-first surface (Star Drops, Language Gaps,
  Enterprise Accounts, etc.).
- **Contract Value Sizing** — estimated annual contract range from enrollment ×
  BPO / CX engagement benchmarks.

## Running locally

The app is a static single file (`index.html`) that fetches
`cms_plans_enriched.json` at runtime. Serve the directory over HTTP:

```bash
python3 -m http.server 4600
# then open http://localhost:4600/index.html
```

(React, ReactDOM, Babel, and Tailwind are loaded from CDNs, so no build step is
required.)

## Data pipeline

- `process_cms.py` — parses the raw CMS Star Ratings tables.
- `enrich_cms.py` — enriches plans with signals, opportunity scores, and
  contract-value estimates → `cms_plans_enriched.json`.

## Data sources

- CMS 2026 Star Ratings Data Tables (Oct 8 2025)
- CMS CPSC Monthly Enrollment (May 2025)
- CAHPS Member Survey · CMS Complaints Database

All ratings and enrollment figures are official CMS published values.

---

_Sales Intelligence · Internal Use Only._
