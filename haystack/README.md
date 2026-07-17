# Haystack RAG Knowledge Base

Haystack-based RAG (Retrieval-Augmented Generation) knowledge base for indexing git repositories and providing semantic search.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Hayhooks                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ REST API    │  │ MCP Server  │  │ Pipelines           │  │
│  │ :1416       │  │ :1417       │  │ - git_indexer       │  │
│  │             │  │             │  │ - rag_query         │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
         │                                    │
         ▼                                    ▼
┌─────────────────┐                  ┌─────────────────┐
│     Milvus      │                  │     Ollama      │
│  Vector Store   │                  │   Embeddings    │
│                 │                  │ nomic-embed-text│
└─────────────────┘                  └─────────────────┘
```

## Components

| Component | Purpose |
|-----------|---------|
| Hayhooks | REST API and MCP server for Haystack pipelines |
| Milvus | Vector database for document embeddings |
| Ollama | LLM server providing embedding model |

## Pipelines

### git_indexer

Clones git repositories and indexes their content into Milvus.

**Supported file types:** `.md`, `.txt`, `.py`, `.yaml`, `.yml`, `.json`, `.go`, `.rs`, `.ts`, `.js`

**Usage via API:**
```bash
curl -X POST http://haystack:1416/git_indexer/run \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/user/repo.git", "branch": "main"}'
```

**Usage via MCP:**
The pipeline is exposed through the MCP gateway.

### rag_query

Performs semantic search over indexed repositories.

**Usage via API:**
```bash
curl -X POST http://haystack:1416/rag_query/run \
  -H "Content-Type: application/json" \
  -d '{"query": "How does authentication work?", "top_k": 5}'
```

**Usage via MCP:**
Available as an MCP tool through the gateway.

## Deployment

### Init Container Pattern

Pipeline dependencies are installed via an init container to ensure all modules are available before Hayhooks starts loading pipelines. This avoids race conditions where Hayhooks would attempt to load pipelines before dependencies are installed.

The init container:
1. Installs Python packages to `/opt/extra-packages`
2. Downloads NLTK data
3. The main container uses `PYTHONPATH` to include these packages

### Pipelines as ConfigMap

Pipeline code is stored in a ConfigMap and mounted to `/pipelines/`. This allows:
- Version-controlled pipeline code in the Helm chart
- Automatic pod restart when pipelines change (via checksum annotation)
- No need to rebuild images for pipeline changes

## Configuration

### values.yaml

```yaml
# Ollama connection
ollama:
  baseURL: "http://ollama.ollama.svc.cluster.local:11434"
  embeddingModel: "nomic-embed-text"

# Repositories to index
repositories:
  - name: ai-knowledge-base
    url: "https://github.com/YOUR_ORG/ai-knowledge-base.git"
    branch: main
```

## Accessing the Service

| Endpoint | Description |
|----------|-------------|
| `http://haystack:1416/status` | Health check |
| `http://haystack:1416/docs` | API documentation |
| `http://haystack:1417/sse` | MCP SSE endpoint |

Via Tailscale: `http://haystack.{tailnet}/`

## Troubleshooting

### Pipelines not loading

Check the hayhooks logs for import errors:
```bash
kubectl logs -n haystack deployment/haystack-hayhooks | grep -i error
```

Common issues:
- Missing Python packages: Check init container completed successfully
- Import errors: Verify package versions are compatible

### Vector store connection issues

Verify Milvus is running:
```bash
kubectl get pods -n haystack -l app.kubernetes.io/component=standalone
```

Check connection from hayhooks:
```bash
kubectl exec -n haystack deployment/haystack-hayhooks -- \
  python -c "from pymilvus import connections; connections.connect(host='haystack-milvus', port=19530); print('Connected')"
```
