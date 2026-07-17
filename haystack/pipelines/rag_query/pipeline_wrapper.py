"""
RAG Query Pipeline

Performs semantic search over indexed git repositories and returns
relevant context with a formatted prompt.

Usage via API:
POST /rag_query/run
{
    "query": "How does the authentication work?",
    "top_k": 5
}

Usage via MCP:
The pipeline is exposed as an MCP tool that Claude can call directly.
"""
import os
from typing import List, Optional

from haystack import Pipeline
from haystack.components.builders import PromptBuilder
from haystack_integrations.components.embedders.ollama import OllamaTextEmbedder
from haystack_integrations.components.retrievers.milvus import MilvusEmbeddingRetriever
from haystack_integrations.document_stores.milvus import MilvusDocumentStore
from hayhooks import BasePipelineWrapper


class PipelineWrapper(BasePipelineWrapper):
    """Pipeline wrapper for RAG queries over the knowledge base."""

    def __init__(self):
        self.milvus_host = os.getenv("MILVUS_HOST", "localhost")
        self.milvus_port = int(os.getenv("MILVUS_PORT", "19530"))
        self.ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.embedding_model = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")

    def setup(self) -> Pipeline:
        """Set up the RAG query pipeline."""
        # Initialize document store
        milvus_uri = f"http://{self.milvus_host}:{self.milvus_port}"
        document_store = MilvusDocumentStore(
            connection_args={"uri": milvus_uri},
            collection_name="git_documents",
        )

        # Create RAG pipeline
        pipeline = Pipeline()

        # Embed the query
        pipeline.add_component(
            "embedder",
            OllamaTextEmbedder(model=self.embedding_model, url=self.ollama_url),
        )

        # Retrieve relevant documents
        pipeline.add_component(
            "retriever", MilvusEmbeddingRetriever(document_store=document_store, top_k=5)
        )

        # Build prompt with context
        prompt_template = """
Based on the following context from the codebase, answer the question.

Context:
{% for doc in documents %}
--- File: {{ doc.meta.file_path }} ({{ doc.meta.repo }}) ---
{{ doc.content }}
{% endfor %}

Question: {{ query }}

Answer:
"""
        pipeline.add_component(
            "prompt_builder", PromptBuilder(template=prompt_template)
        )

        pipeline.connect("embedder.embedding", "retriever.query_embedding")
        pipeline.connect("retriever.documents", "prompt_builder.documents")

        return pipeline

    async def run_api_async(self, query: str, top_k: int = 5) -> dict:
        """Search the indexed git repositories for relevant code and documentation.

        Use this tool to find information in the knowledge base. Returns matching
        documents with file paths, repository names, and relevance scores.

        Args:
            query: Natural language question or search query
            top_k: Number of results to return (default: 5)

        Returns:
            Documents matching the query with context for answering questions
        """
        pipeline = self.setup()

        # Override top_k if specified
        pipeline.get_component("retriever").top_k = top_k

        result = pipeline.run(
            {"embedder": {"text": query}, "prompt_builder": {"query": query}}
        )

        documents = result.get("retriever", {}).get("documents", [])
        prompt = result.get("prompt_builder", {}).get("prompt", "")

        return {
            "query": query,
            "prompt": prompt,
            "documents": [
                {
                    "content": (
                        doc.content[:500] + "..."
                        if len(doc.content) > 500
                        else doc.content
                    ),
                    "file_path": doc.meta.get("file_path"),
                    "repo": doc.meta.get("repo"),
                    "score": doc.score,
                }
                for doc in documents
            ],
        }

    async def run_chat_completion_async(
        self, messages: List[dict], **kwargs
    ) -> dict:
        """OpenAI-compatible chat completion endpoint.

        This allows the pipeline to be used with Open WebUI or other
        OpenAI-compatible clients.
        """
        # Extract the last user message as the query
        query = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                query = msg.get("content", "")
                break

        if not query:
            return {"error": "No user message found"}

        result = await self.run_api_async(query)
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": result["prompt"],
                    }
                }
            ]
        }
