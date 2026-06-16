# Data: training vs. testing, and what's available

## You don't need training data

DefectTriageBot is built on a **pre-trained LLM (Claude Sonnet 4.6)**. There is **no
model training step** — the agent reasons with prompts, not with a model you fit to
labeled data. So you never need a training set.

What you *do* need is **evaluation data**: example defects with known-correct outcomes,
so you can measure whether the agent triages them the way a human expert would (the
plan's targets: severity accuracy ≥ 90%, duplicate precision ≥ 95%, assignment ≥ 85%).

---

## Is there ready-made data on Kaggle / public sources?

Yes — several solid public bug-report datasets exist. They're best for **severity** and
**assignment/component** evaluation at scale:

| Source | What it has | Good for |
|--------|-------------|----------|
| Bugzilla Bug Reports (Kaggle) | ~35k Bugzilla reports | Severity + component testing |
| Eclipse & Mozilla Defect Tracking Dataset (tera-PROMISE / academic) | Curated, genuine defects across the full triage lifecycle: severity, fix-time, component | The classic bug-triage benchmark |
| BugsRepo (Mozilla / Bugzilla, academic) | ~119k curated reports with severity, status, resolution, lifecycle; contributor profiles | Large-scale severity/assignment + status (useful for regression simulation) |
| Software Defect Prediction (Kaggle) | Static **code metrics** with defect labels | Not useful here — it's numeric code metrics, not natural-language bug reports |

> Note: links and exact dataset versions change over time — search Kaggle for "Bugzilla
> bug reports" and "software defect" and confirm the license before using any dataset.

### The catch
None of these public datasets ship the three things this agent is specifically built
around:
- **duplicate pairs** (which report duplicates which),
- **regression labels** (a bug that was fixed and came back), or
- **image attachments** (for the multimodal analyze path).

So public data alone can't exercise the duplicate / regression / multimodal branches.

---

## Our approach: ship hand-built fixtures, scale up later with public data

This repo includes synthetic fixtures that cover **all five canonical scenarios** from
the plan's test table:

- `tests/fixtures/sample_defects.json` — the 5 scenarios:
  1. Critical production outage → CRITICAL → escalate path
  2. Cosmetic staging bug → LOW
  3. Duplicate of an **open** ticket (`DEF-101`) → flag duplicate, LLM skipped
  4. Same symptoms as a **resolved** ticket (`DEF-050`) → regression → analyze
  5. Screenshot attached → multimodal analyze
- `tests/fixtures/seed_backlog.json` — the pre-existing defects the duplicate/regression
  logic matches against (includes open `DEF-101` and resolved `DEF-050`). Seed these into
  the vector store first.

**Recommended path:**
1. Start with these fixtures — they're enough to validate the entire graph end-to-end.
2. Once the agent works, optionally load a slice of a public dataset (e.g. a few hundred
   Bugzilla/Eclipse reports) as a larger **severity + assignment** benchmark.
3. For duplicate/regression at scale, derive pairs yourself (e.g. group reports that share
   a component + similar text, or use the "duplicate of" field where a dataset provides one
   like Bugzilla's resolution metadata).

### How to add a public dataset later
- Download the CSV/JSON and map its fields to our schema:
  `title`, `description`, `stack_trace`, `environment`, `reporter`,
  and a ground-truth `severity` / `component` for scoring.
- Write a small loader in `scripts/` that emits records in the same shape as
  `sample_defects.json`, then run them through the graph and compare predicted vs. actual.
- Keep any downloaded data out of git (add it under `data/`, which is gitignored).
