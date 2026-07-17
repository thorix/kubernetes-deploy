"""
Git Repository Indexer Pipeline

Clones git repositories and indexes their content into Milvus vector store.
Supports: .md, .txt, .py, .yaml, .yml, .json, .go, .rs, .ts, .js files

Usage via API:
POST /git_indexer/run
{
    "repo_url": "https://github.com/user/repo.git",
    "branch": "main"
}
"""
import os
import subprocess
from pathlib import Path
from typing import List, Optional

from haystack import Document, Pipeline
from haystack.components.preprocessors import DocumentSplitter
from haystack.components.writers import DocumentWriter
from haystack.document_stores.types import DuplicatePolicy
from haystack_integrations.components.embedders.ollama import OllamaDocumentEmbedder
from haystack_integrations.document_stores.milvus import MilvusDocumentStore
from hayhooks import BasePipelineWrapper


class PipelineWrapper(BasePipelineWrapper):
    """Pipeline wrapper for git repository indexing."""

    def __init__(self):
        self.milvus_host = os.getenv("MILVUS_HOST", "localhost")
        self.milvus_port = int(os.getenv("MILVUS_PORT", "19530"))
        self.ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.embedding_model = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
        self.repos_dir = Path(os.getenv("REPOS_DIR", "/repos"))

    def setup(self) -> Pipeline:
        """Set up the indexing pipeline."""
        # Initialize document store
        milvus_uri = f"http://{self.milvus_host}:{self.milvus_port}"
        document_store = MilvusDocumentStore(
            connection_args={"uri": milvus_uri},
            collection_name="git_documents",
        )

        # Create indexing pipeline
        pipeline = Pipeline()
        pipeline.add_component(
            "splitter",
            DocumentSplitter(split_by="sentence", split_length=5, split_overlap=1),
        )
        pipeline.add_component(
            "embedder",
            OllamaDocumentEmbedder(model=self.embedding_model, url=self.ollama_url),
        )
        pipeline.add_component(
            "writer",
            DocumentWriter(
                document_store=document_store, policy=DuplicatePolicy.OVERWRITE
            ),
        )

        pipeline.connect("splitter", "embedder")
        pipeline.connect("embedder", "writer")

        return pipeline

    def _clone_or_update_repo(self, repo_url: str, branch: str) -> Path:
        """Clone a new repo or update an existing one."""
        repo_name = repo_url.split("/")[-1].replace(".git", "")
        repo_path = self.repos_dir / repo_name

        if repo_path.exists():
            subprocess.run(
                ["git", "-C", str(repo_path), "fetch", "origin"], check=True
            )
            subprocess.run(
                ["git", "-C", str(repo_path), "reset", "--hard", f"origin/{branch}"],
                check=True,
            )
        else:
            subprocess.run(
                ["git", "clone", "--branch", branch, repo_url, str(repo_path)],
                check=True,
            )

        return repo_path

    def _collect_documents(
        self, repo_path: Path, repo_url: str, branch: str
    ) -> List[Document]:
        """Collect documents from supported file types in the repo."""
        documents = []
        extensions = [
            ".md",
            ".txt",
            ".py",
            ".yaml",
            ".yml",
            ".json",
            ".go",
            ".rs",
            ".ts",
            ".js",
        ]
        repo_name = repo_path.name

        for ext in extensions:
            for file_path in repo_path.rglob(f"*{ext}"):
                # Skip git internals
                if ".git" in str(file_path):
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    rel_path = file_path.relative_to(repo_path)
                    documents.append(
                        Document(
                            content=content,
                            meta={
                                "repo": repo_name,
                                "file_path": str(rel_path),
                                "repo_url": repo_url,
                                "branch": branch,
                            },
                        )
                    )
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")

        return documents

    async def run_api_async(self, repo_url: str, branch: str = "main") -> dict:
        """Clone and index a git repository into the knowledge base.

        Indexes code files (.py, .go, .rs, .ts, .js) and documentation (.md, .txt, .yaml)
        for semantic search via the rag_query tool.

        Args:
            repo_url: Git repository URL (e.g., https://github.com/org/repo.git)
            branch: Branch to index (default: main)

        Returns:
            Status with count of documents and chunks indexed
        """
        # Clone or update repo
        repo_path = self._clone_or_update_repo(repo_url, branch)
        repo_name = repo_path.name

        # Collect documents
        documents = self._collect_documents(repo_path, repo_url, branch)

        if not documents:
            return {
                "status": "warning",
                "repo": repo_name,
                "message": "No supported files found in repository",
                "documents_indexed": 0,
            }

        # Run pipeline
        pipeline = self.setup()
        result = pipeline.run({"splitter": {"documents": documents}})

        return {
            "status": "success",
            "repo": repo_name,
            "documents_indexed": len(documents),
            "chunks_written": result.get("writer", {}).get("documents_written", 0),
        }
