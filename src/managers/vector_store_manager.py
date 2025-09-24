import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any
import numpy as np

logger = logging.getLogger(__name__)

class LocalEmbeddings:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None
        self.embedding_dimensions = None

    def _load_model(self):
        from sentence_transformers import SentenceTransformer
        if self.model is None:
            self.model = SentenceTransformer(self.model_name)
            self.embedding_dimensions = self.model.get_sentence_embedding_dimension()

    def generate_embedding(self, text: str) -> List[float]:
        if self.model is None:
            self._load_model()
        emb = self.model.encode(text, convert_to_tensor=False)
        return emb.tolist() if hasattr(emb, "tolist") else list(emb)

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        denom = (np.linalg.norm(v1) * np.linalg.norm(v2))
        return 0.0 if denom == 0 else float(np.dot(v1, v2) / denom)

class VectorStoreManager:
    """Vector store manager using local embeddings + MongoDB Atlas Vector Search."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.embedder = LocalEmbeddings(model_name)
        self._closed = False

    async def __aenter__(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.embedder._load_model)
        return self

    async def __aexit__(self):
        self._closed = True

    async def setup_vector_index(self, collection, index_name: str = "vector_index"):
        if self.embedder.embedding_dimensions is None:
            self.embedder._load_model()

        index_definition = {
            "name": index_name,
            "definition": {
                "mappings": {
                    "dynamic": True,
                    "fields": {
                        "embedding": {
                            "type": "knnVector",
                            "dimensions": self.embedder.embedding_dimensions,
                            "similarity": "cosine"
                        }
                    }
                }
            }
        }

        try:
            await collection.create_search_index(index_definition)
            logger.info(f"✅ Vector search index '{index_name}' created or already exists")
        except Exception as e:
            logger.warning(f"⚠️ Vector index creation failed (may already exist or be unsupported on this cluster): {e}")

    def create_searchable_text(self, entry: Dict[str, Any]) -> str:
        fields = [
            entry.get('victimCompany', ''),
            entry.get('industry', ''),
            entry.get('countryOfCompany', ''),
            entry.get('ransomwareGroup', ''),
            entry.get('description', '')
        ]
        return ' '.join(str(f).strip() for f in fields if f)

    async def vector_search(self, collection, query_vector: List[float],
                            limit: int = 5, threshold: float = 0.85,
                            index_name: str = "vector_index") -> List[Dict]:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": index_name,
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": min(100, limit * 10),
                    "limit": limit
                }
            },
            {
                "$project": {
                    "victimCompany": 1,
                    "industry": 1,
                    "countryOfCompany": 1,
                    "ransomwareGroup": 1,
                    "description": 1,
                    "attackDate": 1,
                    "discovered": 1,
                    "companyWebDomain": 1,
                    "searchable_text": 1,
                    "created_at": 1,
                    "score": {"$meta": "vectorSearchScore"}
                }
            },
            {"$match": {"score": {"$gte": threshold}}}
        ]
        try:
            return await collection.aggregate(pipeline).to_list(length=limit)
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []
        
    async def normalize_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        if "victimCompany" in entry and entry["victimCompany"]:
            entry["victimCompany"] = entry["victimCompany"].strip().lower()
        return entry

    async def find_similar_entries(self, collection, entry: Dict[str, Any],
                                   threshold: float = 0.85, limit: int = 3) -> List[Dict]:
        searchable_text = self.create_searchable_text(entry)
        if not searchable_text.strip():
            logger.warning("Entry has no searchable content")
            return []
        emb = self.embedder.generate_embedding(searchable_text)
        return await self.vector_search(collection, emb, limit=limit, threshold=threshold)

    async def store_entry_with_embedding(self, collection, entry: Dict[str, Any],
                                         similarity_threshold: float = 0.85) -> Dict[str, Any]:
        try:
            entry = await self.normalize_entry(entry) 
            similar = await self.find_similar_entries(collection, entry, threshold=similarity_threshold)
            if similar:
                top = similar[0]
                return {'stored': False, 'entry': top, 'similarity_score': top.get('score', 0.0)}

            searchable_text = self.create_searchable_text(entry)
            emb = self.embedder.generate_embedding(searchable_text)

            doc = {**entry, 'embedding': emb, 'searchable_text': searchable_text, 'created_at': datetime.utcnow().isoformat()}
            result = await collection.insert_one(doc)

            returned = doc.copy()
            returned.pop('embedding', None)
            returned['_id'] = result.inserted_id
            return {'stored': True, 'entry': returned, 'similarity_score': None}

        except Exception as e:
            logger.error(f"Error storing entry with embedding: {e}")
            result = await collection.insert_one(entry)
            fallback = entry.copy()
            fallback['_id'] = result.inserted_id
            return {'stored': True, 'entry': fallback, 'similarity_score': None}
