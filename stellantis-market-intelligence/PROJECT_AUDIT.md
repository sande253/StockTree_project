# Project Phase Audit

Reviewed 2026-10-23 against `stellantis-market-impact-intelligence-master-prompt.md`, repository notes, current code, and focused tests. “Implemented” means the code path exists; it does not imply adequate data coverage or validated business output.

## Phase Status

| Phase | Status | Evidence and gap |
|---|---|---|
| 1. Company universe | Implemented | YAML-configured universe; complete market-data coverage across that universe has not been verified. |
| 2. Market ingestion | Implemented | yfinance ingestion and DuckDB/Parquet persistence; refresh cadence and completeness are operational concerns. |
| 3. Returns and volatility | Implemented | Reusable calculations and stored features. |
| 4. Event detection | Implemented | Configurable STLA event rules and persistence. |
| 5. Correlations | Implemented | Statistical correlation pipeline exists; results must remain separate from business links. |
| 6. Event study | Implemented | Event windows and market-model abnormal returns exist. |
| 7. Market/sector context | Implemented | Benchmark comparison exists; context is missing when benchmark history is missing. |
| 8. News ingestion | Limited | Parser and ingestion pipeline exist, but configured coverage is essentially an SEC ownership-filings feed, not broad catalyst news. |
| 9. Event classification | Implemented, weak inputs | Rule-based classifier exists; sparse, non-overlapping news means many events remain “Other.” |
| 10. News/event correlation | Implemented, no useful current coverage | Ranking and cautious catalyst wording exist; available articles do not overlap the event dates, so no catalyst is established. |
| 11. Relationship graph | Corrected, limited scope | Graph code exists. Correlation-derived “supplier/partner” edges were invalid; the seed now retains only 14 official Stellantis brands. |
| 12. Business relationship analysis | Implemented, limited evidence | Profiles work for documented edges; current seed has brands, not verified suppliers or partners. |
| 13. Business + stock profile | Implemented, sparse market coverage | Merge logic exists; most brand entities have no separately traded ticker, so market fields are unavailable. |
| 14. Supply-chain propagation | Implemented, no multi-hop evidence | Traversal works, but the current documented graph has no evidenced supplier chain to propagate. |
| 15. Lead/lag analysis | Implemented, insufficient history | Statistical logic exists; available history does not support useful significant results. |
| 16. Regime detection | Implemented, insufficient history | Regime logic exists; available time span is too short to demonstrate multi-period changes. |
| 17. Event fingerprinting | Implemented, sparse upstream fields | Fingerprints persist, but benchmark, peer, and recovery fields can be null. |
| 18. Historical similarity | Implemented with insufficient-data guard | Sparse/constant fingerprints previously produced identical 100% matches. Similarity now returns no ranking when the corpus lacks distinguishing numeric or text features. |
| 19. Vector database | Implemented with deviation | FAISS index uses TF-IDF features rather than neural embeddings; indexed corpus is limited. |
| 20. RAG | Implemented with approved deviation | Groq-hosted synthesis replaces the planned local model; retrieval uses TF-IDF. API/model availability is external. |
| 21. Investigation agent | Implemented, data-limited | Fixed Python analysis pipeline and optional synthesis exist; useful conclusions depend on sparse news and relationship evidence. |
| 22. Exposure score | Implemented, low differentiation | Transparent score exists; brands can receive identical scores because their documented graph position and evidence are identical. |
| 23. Dashboard | Implemented, UX still in progress | Seven requested pages plus Status exist. Shared layout, truthful freshness labels, mobile behavior, and Event Explorer filtering were improved in this review. |
| 24. API | Implemented with approved deviation | Flask is used instead of FastAPI, as requested in repository notes; it shares service-layer logic with the dashboard. |
| 25. Business report | Implemented, corrected in this review | Similar-event lookup previously used the wrong function arguments; benchmark absence was treated as zero and a raw difference was mislabeled abnormal return. |
| 26. Executive insights | Partial | Deterministic findings exist inside reports; this is not a separately validated insight-generation workflow. |
| 27. Database refinement | Partial | Core tables exist, but the requested `event_similarity`, `investigations`, and `investigation_sources` tables are absent; foreign-key enforcement is also not demonstrated. |
| 28. Error handling | Partial | API-level handling exists, but prior status reporting silently returned zero for failed queries. This review fixes that path; full failure-mode coverage remains. |
| 29. Testing | Baseline passing, coverage incomplete | The `.env`-dependent test is now hermetic; the current full suite passes (160 tests). This does not cover every external-data, browser, or failure-mode scenario. |
| 30. User experience | In progress | The workflow pages exist, but this review only addresses common shell, hierarchy, responsive layout, and one missing filter. Browser validation and broader usability work remain. |
| 31. Core business workflow | Partial | Services are connected, but the present news and graph data cannot support the complete catalyst-to-multi-hop-supply-chain workflow. |
| 32. Final product criteria | Not met yet | The app runs as a research prototype, but sparse evidence, limited data coverage, and incomplete end-to-end validation prevent the promised full answer. |

Items 33-36 in the source prompt describe analytical principles, implementation order, development rules, and final success criteria rather than additional feature modules. Those principles—especially no fabricated data, evidence-backed relationships, and no correlation-as-causation—are the standard used in this audit.

## Root Causes

1. `scripts/fetch_live_ecosystem.py` assigned supplier/competitor labels to a hard-coded ticker list, then wrote observed price correlations into `config/relationships.yaml` as business relationships. `scripts/update_graph_from_live_data.py` promoted those rows to high-confidence edges. A market-data URL cannot substantiate a business relationship.
2. The application’s sparse source coverage was mistaken for a complete intelligence workflow. SEC ownership filings do not provide broad event-catalyst coverage, and a brand-only graph cannot produce supplier-chain propagation.
3. Completion/readiness documents reported unverified availability, accuracy, live-server, and production claims. They also disagreed with the actual Flask/Groq/TF-IDF implementation.
4. The report generator called the current similarity function with an obsolete interface and converted absent benchmark values into zero, creating empty similarity output and misleading context.
5. Tests were not hermetic around `.env`; a test intended to skip Groq could load a developer key and make an external call.

## Changes In This Review

- Removed the correlation-to-relationship writer and rewrote the graph updater to seed only evidence-backed YAML.
- Removed unsupported company edges from the seed, retaining the 14 brands listed on Stellantis’ official brands page.
- Rejected the known invalid market-analysis provenance and filtered its legacy rows from graph and relationship API reads without deleting warehouse data.
- Fixed Status counts to query `market_events`, close database connections, and report unavailable data honestly; health now checks all vector-index artifacts.
- Fixed report similarity arguments and missing-benchmark handling; renamed the simple benchmark difference to `market_adjusted_return` and removed causal wording.
- Made the no-Groq agent test isolated from the developer `.env`.
- Suppressed misleading perfect similarity rankings when event fingerprints lack distinguishing features.
- Standardized the dashboard shell, corrected freshness claims, and added Event Explorer filtering.
- Corrected README stack claims and marked earlier “complete” and “production-ready” documents as historical, unverified snapshots.

## Still Required

- Expand tests beyond the current passing unit/API suite to cover external-data, browser, and failure-mode scenarios.
- Validate all dashboard pages at desktop and mobile widths in a browser.
- Add reliable, permitted catalyst sources with dates overlapping the ingested market history; do not infer causes when evidence is absent.
- Expand and verify business relationships from primary evidence before enabling supply-chain claims.
- Expand historical fingerprints with reliable, varied evidence; current sparse data now correctly produces no similarity ranking.
- Complete the missing schema/contracts and end-to-end workflow tests before claiming Phase 27 or Phases 29-32 complete.
- Treat the app as a research prototype until deployment, security, availability, backup, and performance checks have actually been run.
