# Codebase Intelligence Engine (CBI)

Read-only analyzer for Python repositories: AST parsing, dependency graph, cyclomatic complexity, code smells, Git-history mining and ranked, explainable hotspots. It never executes the analyzed code.

**Live demo:** `https://<your-username>.github.io/<repo-name>/` (demo data: analysis of psf/requests)

## Run it on your own repo

```bash
python -m cbi /path/to/python/repo -o report.json
python -m http.server
```

Open http://localhost:8000. Needs Python 3.10+, no dependencies; Git is optional.
On the hosted site, open *Repository Analysis*, click **Browse** and pick your `report.json`.

## Publish on GitHub Pages

Push the repo, then Settings > Pages > Deploy from branch > `main` and `/ (root)`.
`index.html` (the dashboard) and `report.json` (demo data) sit at the repo root.

## How it works

| Stage | Where |
|---|---|
| Ingestion | `cbi/analyzer.py` `analyze()` |
| Static analysis (AST, LOC, complexity, smells, imports) | `parse()` |
| Git mining | `git()` |
| Insight engine: 0.35 complexity + 0.30 churn + 0.20 smells + 0.15 fan-in | `analyze()` |
| Reports and views | `index.html` |

Course project 21CSC203P-APP, SRM Institute of Science and Technology, Ramapuram.
