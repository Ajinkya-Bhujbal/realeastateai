"""
RAG module - ChromaDB + sentence-transformers for property recommendations + knowledge base.
Uses a small embedding model to keep RAM low.
"""
import os
import json
import glob
import chromadb
from chromadb.config import Settings

# Lazy-load sentence transformer to save RAM at startup
_embedder = None
CHROMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "chroma_db")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
KB_DIR = os.path.join(DATA_DIR, "knowledge_base")


def _get_embedder():
    """Lazy-load the embedding model. Uses multilingual model for Hinglish support (~120MB, light)."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _embedder


def get_chroma_client():
    """Get ChromaDB persistent client."""
    os.makedirs(CHROMA_DIR, exist_ok=True)
    return chromadb.PersistentClient(path=CHROMA_DIR)


# ─── Properties Collection ─────────────────────────

def get_or_create_collection(client=None):
    """Get or create the properties collection."""
    if client is None:
        client = get_chroma_client()
    return client.get_or_create_collection(
        name="properties",
        metadata={"hnsw:space": "cosine"},
    )


def embed_text(text: str) -> list:
    """Generate embedding for a text string."""
    model = _get_embedder()
    return model.encode(text).tolist()


def embed_texts(texts: list) -> list:
    """Generate embeddings for multiple texts."""
    model = _get_embedder()
    return model.encode(texts).tolist()


def index_property(prop: dict, collection=None):
    """Index a single property into ChromaDB."""
    if collection is None:
        collection = get_or_create_collection()

    text = _property_to_text(prop)
    embedding = embed_text(text)

    collection.upsert(
        ids=[str(prop.get("id", prop.get("title", "unknown")))],
        documents=[text],
        embeddings=[embedding],
        metadatas=[{
            "title": str(prop.get("title", "")),
            "location": str(prop.get("location", "")),
            "price": float(prop.get("price", 0)),
            "bedrooms": int(prop.get("bedrooms", 0)),
            "property_type": str(prop.get("property_type", "")),
            "area_sqft": float(prop.get("area_sqft", 0)),
        }],
    )


def index_properties_bulk(properties: list):
    """Index multiple properties into ChromaDB."""
    collection = get_or_create_collection()

    ids = []
    texts = []
    metadatas = []

    for prop in properties:
        text = _property_to_text(prop)
        texts.append(text)
        ids.append(str(prop.get("id", prop.get("title", "unknown"))))
        metadatas.append({
            "title": str(prop.get("title", "")),
            "location": str(prop.get("location", "")),
            "price": float(prop.get("price", 0)),
            "bedrooms": int(prop.get("bedrooms", 0)),
            "property_type": str(prop.get("property_type", "")),
            "area_sqft": float(prop.get("area_sqft", 0)),
        })

    all_embeddings = embed_texts(texts)

    collection.upsert(
        ids=ids,
        documents=texts,
        embeddings=all_embeddings,
        metadatas=metadatas,
    )
    return len(ids)


def search_properties(query: str, n_results: int = 5, filters: dict = None) -> list:
    """Search properties using semantic similarity."""
    collection = get_or_create_collection()
    query_embedding = embed_text(query)

    where_filter = None
    if filters:
        conditions = []
        if "property_type" in filters and filters["property_type"]:
            conditions.append({"property_type": {"$eq": filters["property_type"]}})
        if "min_price" in filters and filters["min_price"]:
            conditions.append({"price": {"$gte": float(filters["min_price"])}})
        if "max_price" in filters and filters["max_price"]:
            conditions.append({"price": {"$lte": float(filters["max_price"])}})
        if "bedrooms" in filters and filters["bedrooms"]:
            conditions.append({"bedrooms": {"$eq": int(filters["bedrooms"])}})

        if len(conditions) == 1:
            where_filter = conditions[0]
        elif len(conditions) > 1:
            where_filter = {"$and": conditions}

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, 10),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, 10),
            include=["documents", "metadatas", "distances"],
        )

    properties = []
    if results and results["metadatas"] and results["metadatas"][0]:
        for i, meta in enumerate(results["metadatas"][0]):
            prop = dict(meta)
            prop["relevance"] = 1 - results["distances"][0][i] if results["distances"][0] else 0
            prop["document"] = results["documents"][0][i] if results["documents"][0] else ""
            properties.append(prop)

    return properties


def load_sample_properties():
    """Load sample properties from JSON file and index them."""
    json_path = os.path.join(DATA_DIR, "properties.json")
    if not os.path.exists(json_path):
        print(f"No sample properties file at {json_path}")
        return 0

    with open(json_path, "r", encoding="utf-8") as f:
        properties = json.load(f)

    count = index_properties_bulk(properties)
    print(f"Indexed {count} properties into ChromaDB")
    return count


def _property_to_text(prop: dict) -> str:
    """Convert a property dict to a searchable text string."""
    parts = [
        prop.get("title", ""),
        f"Location: {prop.get('location', '')}",
        f"Price: {prop.get('price', '')} Lakhs",
        f"Type: {prop.get('property_type', '')}",
        f"Bedrooms: {prop.get('bedrooms', '')} BHK",
        f"Area: {prop.get('area_sqft', '')} sqft",
        f"Builder: {prop.get('builder', '')}",
        f"Amenities: {prop.get('amenities', '')}",
        prop.get("description", ""),
    ]
    return " | ".join([p for p in parts if p and str(p).strip()])


# ─── Knowledge Base Collection ─────────────────────

def get_or_create_kb_collection(client=None):
    """Get or create the knowledge base collection."""
    if client is None:
        client = get_chroma_client()
    return client.get_or_create_collection(
        name="knowledge_base",
        metadata={"hnsw:space": "cosine"},
    )


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list:
    """Split text into overlapping chunks for better retrieval."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
    return chunks


def index_kb_file(filepath: str) -> int:
    """Index a single .txt or .md file into the KB collection."""
    collection = get_or_create_kb_collection()

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return 0

    if not content.strip():
        return 0

    filename = os.path.basename(filepath)
    chunks = _chunk_text(content)

    if not chunks:
        return 0

    ids = [f"{filename}__chunk_{i}" for i in range(len(chunks))]
    metadatas = [{"source": filename, "chunk_index": i} for i in range(len(chunks))]
    embeddings = embed_texts(chunks)

    collection.upsert(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    return len(chunks)


def index_kb_folder() -> dict:
    """Index all .txt and .md files in data/knowledge_base/."""
    os.makedirs(KB_DIR, exist_ok=True)

    files = glob.glob(os.path.join(KB_DIR, "*.txt")) + glob.glob(os.path.join(KB_DIR, "*.md"))
    total_chunks = 0
    indexed_files = []

    for f in files:
        count = index_kb_file(f)
        total_chunks += count
        indexed_files.append({"file": os.path.basename(f), "chunks": count})
        print(f"KB indexed: {os.path.basename(f)} -> {count} chunks")

    return {"files": len(files), "total_chunks": total_chunks, "details": indexed_files}


def search_kb(query: str, n_results: int = 3) -> list:
    """Search the knowledge base using semantic similarity."""
    collection = get_or_create_kb_collection()

    try:
        count = collection.count()
        if count == 0:
            return []
    except Exception:
        return []

    query_embedding = embed_text(query)

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, count),
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        return []

    kb_results = []
    if results and results["documents"] and results["documents"][0]:
        for i, doc in enumerate(results["documents"][0]):
            kb_results.append({
                "text": doc,
                "source": results["metadatas"][0][i].get("source", "") if results["metadatas"][0] else "",
                "relevance": 1 - results["distances"][0][i] if results["distances"][0] else 0,
            })

    return kb_results


def get_kb_status() -> dict:
    """Get knowledge base status."""
    os.makedirs(KB_DIR, exist_ok=True)
    files = glob.glob(os.path.join(KB_DIR, "*.txt")) + glob.glob(os.path.join(KB_DIR, "*.md"))

    try:
        collection = get_or_create_kb_collection()
        chunk_count = collection.count()
    except Exception:
        chunk_count = 0

    return {
        "files": len(files),
        "file_names": [os.path.basename(f) for f in files],
        "indexed_chunks": chunk_count,
        "kb_path": KB_DIR,
    }
