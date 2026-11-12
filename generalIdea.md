# Stellantis Market Impact Intelligence
## Complete Business Prototype — Master Build Prompt

You are a senior financial-data engineer, quantitative analyst, AI engineer, backend engineer, and product architect.

Build a complete business-oriented prototype called:

# Stellantis Market Impact Intelligence

---

# 1. BUSINESS OBJECTIVE

Build an intelligence platform that helps Stellantis understand how events affecting Stellantis propagate through the broader automotive ecosystem.

The core business question is:

> "When something materially affects Stellantis, which other companies may be affected, how strongly have they historically reacted, what business relationship connects them, and what evidence explains the relationship?"

The system should go beyond simple stock correlation.

It should combine:

- Stock-market data
- Event detection
- Statistical analysis
- Event studies
- Market/sector comparison
- News intelligence
- Company filings
- Corporate relationships
- Supplier intelligence
- Supply-chain analysis
- Competitor analysis
- Historical event analysis
- Knowledge graphs
- Semantic search
- RAG
- Local AI
- Automated investigation
- Business reporting

The final product should feel like an internal **market and ecosystem intelligence tool** for Stellantis.

---

# 2. IMPORTANT SCOPE

This is a BUSINESS PROTOTYPE.

Focus on:

- Business value
- Accuracy
- Explainability
- Evidence
- Useful insights
- Functioning backend
- Working dashboard
- Clean architecture
- Good user experience

DO NOT build:

- Kubernetes
- Docker
- Terraform
- Prometheus
- Grafana
- OpenTelemetry
- CI/CD infrastructure
- Cloud infrastructure
- Production deployment infrastructure

The entire system should run locally.

---

# 3. COST REQUIREMENT

The project must be buildable at ₹0.

Prefer free/public sources and open-source software.

Use:

- Free market data
- Public news/RSS sources
- Public company filings
- Public company announcements
- Local databases
- Local vector database
- Local embeddings
- Local LLM

Do not require paid APIs.

Do not require cloud services.

If a data source is unavailable, fail gracefully.

Never fabricate data.

---

# 4. TECHNOLOGY STACK

Use:

## Backend

- Python
- FastAPI
- Pydantic

## Data

- Pandas
- NumPy
- DuckDB
- Parquet

## Statistical Analysis

- SciPy
- Statsmodels
- Scikit-learn

## Knowledge Graph

- NetworkX

## Vector Search

- FAISS or Chroma

## Embeddings

- Sentence Transformers

## Local AI

- Ollama
- Local open-source LLM

## Dashboard

- Streamlit

---

# 5. HIGH-LEVEL ARCHITECTURE

```text
                         DATA SOURCES
                              |
             +----------------+----------------+
             |                |                |
             v                v                v
        Market Data         News          Company Filings
             |                |                |
             +----------------+----------------+
                              |
                              v
                       DATA INGESTION
                              |
                              v
                       PARQUET / DUCKDB
                              |
             +----------------+----------------+
             |                |                |
             v                v                v
       Event Engine      Analytics       News Engine
             |                |                |
             +----------------+----------------+
                              |
                              v
                     IMPACT ANALYSIS
                              |
             +----------------+----------------+
             |                |                |
             v                v                v
       Correlation       Event Study     Anomaly Detection
             |                |                |
             +----------------+----------------+
                              |
                              v
                  CORPORATE RELATIONSHIP GRAPH
                              |
                              v
                      VECTOR DATABASE
                              |
                              v
                         LOCAL RAG
                              |
                              v
                    AI INVESTIGATION AGENT
                              |
                              v
                         FASTAPI
                              |
                              v
                       STREAMLIT UI