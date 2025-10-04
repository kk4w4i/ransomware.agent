import asyncio
import json
import os
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import requests
from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore

from src.managers.vector_store_manager import LocalEmbeddings

try:
    import tldextract
except Exception:
    tldextract = None

# Map ransomwarelive_field -> ransomwareAgent_field
FIELD_MAP = {
    "group": ("group", "ransomwareGroup"),
    "victim": ("victim", "victimCompany"),
    "domain": ("domain", "companyWebDomain"),
    "attack_date": ("attackdate", "attackDate"),
    "country": ("country", "countryOfCompany"),
    "description": ("description", "description"),
    "discovered": ("discovered", "discovered"),
    "industry": {"activity", "industry"}
}

DEFAULT_EVAL_FIELDS = [
    "victim",
    "group",
    "domain",
    "country",
    "description",
    "industry"
]

ATTACK_DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d"
]
DISCOVERED_FORMATS = [
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d"
]


_embedder: Optional[LocalEmbeddings] = None
_embedding_cache: Dict[str, np.ndarray] = {}


def _get_embedder() -> LocalEmbeddings:
    global _embedder
    if _embedder is None:
        _embedder = LocalEmbeddings()
    return _embedder


def _get_embedding(text: Optional[str]) -> Optional[np.ndarray]:
    if not text:
        return None
    key = text.strip().lower()
    cached = _embedding_cache.get(key)
    if cached is not None:
        return cached

    embedder = _get_embedder()
    try:
        embedding = np.array(embedder.generate_embedding(text), dtype=np.float32)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Embedding generation failed: {exc}")
        return None

    _embedding_cache[key] = embedding
    return embedding


def _cosine_similarity(vec_a: Optional[np.ndarray], vec_b: Optional[np.ndarray]) -> float:
    if vec_a is None and vec_b is None:
        return 1.0
    if vec_a is None or vec_b is None:
        return 0.0
    denom = float(np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)


def _vector_similarity(a: Optional[str], b: Optional[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    emb_a = _get_embedding(a)
    emb_b = _get_embedding(b)
    return _cosine_similarity(emb_a, emb_b)

def _parse_dt(s: Optional[str], formats):
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

def _norm_text(x: Any) -> Optional[str]:
    if x is None:
        return None
    if not isinstance(x, str):
        return str(x)
    s = x.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _norm_domain(x: Any) -> Optional[str]:
    s = _norm_text(x)
    if not s:
        return None
    s = re.sub(r"^[a-z]+://", "", s)
    s = s.split("/")[0]
    s = s.split(":")[0]
    if tldextract:
        ext = tldextract.extract(s)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}"
        if ext.domain:
            return ext.domain
    return s[4:] if s.startswith("www.") else s

def _soft_ratio(a: Optional[str], b: Optional[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()

def _date_equal_by_day(a: Optional[datetime], b: Optional[datetime]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return 1.0 if (a.date() == b.date()) else 0.0

def extract_company_names(docs: List[Dict[str, Any]], key: str) -> set:
    return set(_norm_text(d[key]) for d in docs if key in d and d[key] not in (None, "", []))

async def eval_group(
    group_name: str,
    live_db_name: str,
    agent_db_name: str,
    live_coll_name: str,
    agent_coll_name: str,
    mongo_uri_env: str = "MONGODB_URI",
    fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Evaluate agent vs ransomware.live for a given group, with schema-aware normalization.
    Does global evaluation for all victimCompany values and per-victim company field comparison.
    """
    uri = os.getenv(mongo_uri_env)
    client = AsyncIOMotorClient(uri)

    live_coll = client[live_db_name][live_coll_name]
    agent_coll = client[agent_db_name][agent_coll_name]

    await import_group_victims(group_name, live_coll)

    live_group_name = await _best_group_name(group_name, live_coll, "group")
    agent_group_name = await _best_group_name(group_name, agent_coll, "ransomwareGroup")

    live_docs = await live_coll.find({
        "group": {"$regex": f"^{re.escape(live_group_name)}$", "$options": "i"}
    }).to_list(length=10000)
    agent_docs = await agent_coll.find({
        "ransomwareGroup": {"$regex": f"^{re.escape(agent_group_name)}$", "$options": "i"}
    }).to_list(length=10000)

    live_victim_map: Dict[str, Dict[str, Any]] = {}
    live_victim_profiles: List[Tuple[str, Optional[np.ndarray], Dict[str, Any]]] = []
    for live_doc in live_docs:
        live_name = _norm_text(live_doc.get("victim"))
        if not live_name:
            continue
        if live_name not in live_victim_map:
            live_victim_map[live_name] = live_doc
        live_victim_profiles.append((live_name, _get_embedding(live_name), live_doc))

    result = {
        "groupRequested": group_name,
        "groupMatched": {
            "live": live_group_name,
            "agent": agent_group_name,
        },
        "counts": {"live_docs": len(live_docs), "agent_docs": len(agent_docs)},
    }

    selected_fields: List[str]
    if isinstance(fields, str):
        selected_fields = [fields]
    else:
        selected_fields = list(fields) if fields else DEFAULT_EVAL_FIELDS

    allowed_fields = [f for f in selected_fields if f in FIELD_MAP]
    if not allowed_fields:
        allowed_fields = list(DEFAULT_EVAL_FIELDS)

    # --- Per victimCompany in agent collection: per-field eval ---
    detailed_per_victim = []
    unmatched_victims = []
    all_exact_scores = []
    all_soft_scores = []
    all_vector_scores = []
    field_scores = {}  # Track scores by field

    for agent_doc in agent_docs:
        agent_company = _norm_text(agent_doc.get("victimCompany"))
        if not agent_company:
            continue
        
        live_doc = live_victim_map.get(agent_company)
        match_type = "exact" if live_doc else "vector"
        best_vector_score = 0.0

        if live_doc is None:
            agent_embedding = _get_embedding(agent_company)
            if agent_embedding is None:
                unmatched_victims.append(agent_company)
                continue

            best_match_doc = None
            best_vector_score = -1.0
            for live_name, live_embedding, candidate_doc in live_victim_profiles:
                if live_embedding is None:
                    continue
                score = _cosine_similarity(agent_embedding, live_embedding)
                if score > best_vector_score:
                    best_vector_score = score
                    best_match_doc = candidate_doc

            if best_match_doc is None:
                unmatched_victims.append(agent_company)
                continue

            live_doc = best_match_doc

        victim_vector_score = _vector_similarity(
            agent_company,
            _norm_text(live_doc.get("victim")),
        )

        per_field_victim, exacts_victim, softs_victim, vectors_victim = [], [], [], []
        
        for canon in allowed_fields:
            live_k, agent_k = FIELD_MAP[canon]
            live_val = live_doc.get(live_k)
            agent_val = agent_doc.get(agent_k)
            
            if canon in ("victim", "group", "description", "industry"):
                ln = _norm_text(live_val)
                an = _norm_text(agent_val)
                exact = 1.0 if (ln and an and ln == an) else 0.0
                soft = _soft_ratio(ln, an)
                vector = _vector_similarity(ln, an)
            elif canon == "country":
                ln = _norm_text(live_val)
                an = _norm_text(agent_val)
                exact = 1.0 if (ln and an and ln == an) else 0.0
                soft = _soft_ratio(ln, an)
                vector = _vector_similarity(ln, an)
            elif canon == "domain":
                ln = _norm_domain(live_val)
                an = _norm_domain(agent_val)
                exact = 1.0 if (ln and an and ln == an) else 0.0
                soft = _soft_ratio(ln, an)
                vector = _vector_similarity(ln, an)
            elif canon in ("attack_date", "discovered"):
                if canon == "attack_date":
                    ld_val = _parse_dt(live_val, ATTACK_DATE_FORMATS)
                    ad_val = _parse_dt(agent_val, ATTACK_DATE_FORMATS)
                else:
                    ld_val = _parse_dt(live_val, DISCOVERED_FORMATS)
                    ad_val = _parse_dt(agent_val, DISCOVERED_FORMATS)
                exact = _date_equal_by_day(ld_val, ad_val)
                soft = exact
                vector = _vector_similarity(
                    ld_val.isoformat() if ld_val else None,
                    ad_val.isoformat() if ad_val else None,
                )
            else:
                ln = _norm_text(live_val)
                an = _norm_text(agent_val)
                exact = 1.0 if (ln and an and ln == an) else 0.0
                soft = _soft_ratio(ln, an)
                vector = _vector_similarity(ln, an)
            
            # Track field-specific scores
            if canon not in field_scores:
                field_scores[canon] = {"exact": [], "soft": [], "vector": []}
            field_scores[canon]["exact"].append(exact)
            field_scores[canon]["soft"].append(soft)
            field_scores[canon]["vector"].append(vector)
                
            per_field_victim.append({
                "field": canon,
                "live_value": live_val,
                "agent_value": agent_val,
                "exact": round(exact, 4),
                "soft": round(soft, 4),
                "vector": round(vector, 4),
            })
            exacts_victim.append(exact)
            softs_victim.append(soft)
            vectors_victim.append(vector)
        
        all_exact_scores.extend(exacts_victim)
        all_soft_scores.extend(softs_victim)
        all_vector_scores.extend(vectors_victim)
        
        detailed_per_victim.append({
            "victimCompany": agent_company,
            "scores": {
                "exact_accuracy": round(sum(exacts_victim)/len(exacts_victim), 4),
                "soft_similarity": round(sum(softs_victim)/len(softs_victim), 4),
                "vector_similarity": round(sum(vectors_victim)/len(vectors_victim), 4),
            },
            "match": {
                "type": match_type,
                "victim_vector": round(victim_vector_score, 4),
                "matched_victim": _norm_text(live_doc.get("victim")),
            },
            "per_field": per_field_victim
        })

    # Calculate aggregate scores
    aggregate_exact_score = round(sum(all_exact_scores)/len(all_exact_scores), 4) if all_exact_scores else 0.0
    aggregate_soft_score = round(sum(all_soft_scores)/len(all_soft_scores), 4) if all_soft_scores else 0.0
    aggregate_vector_score = round(sum(all_vector_scores)/len(all_vector_scores), 4) if all_vector_scores else 0.0

    # Calculate per-field aggregate scores
    field_aggregate_scores = {}
    for field, scores in field_scores.items():
        exact_scores = scores["exact"]
        soft_scores = scores["soft"]
        vector_scores = scores["vector"]
        field_aggregate_scores[field] = {
            "exact_accuracy": round(sum(exact_scores)/len(exact_scores), 4) if exact_scores else 0.0,
            "soft_similarity": round(sum(soft_scores)/len(soft_scores), 4) if soft_scores else 0.0,
            "vector_similarity": round(sum(vector_scores)/len(vector_scores), 4) if vector_scores else 0.0,
            "sample_count": len(exact_scores)
        }

    result["detailed_per_victim"] = detailed_per_victim
    result["per_victim_match_count"] = len(detailed_per_victim)
    result["unmatched_victims"] = unmatched_victims
    result["unmatched_count"] = len(unmatched_victims)
    result["aggregate_scores"] = {
        "exact_accuracy": aggregate_exact_score,
        "soft_similarity": aggregate_soft_score,
        "vector_similarity": aggregate_vector_score,
    }
    result["field_aggregate_scores"] = field_aggregate_scores

    return result


async def import_group_victims(
    group_name: str,
    collection,
    save_file: bool = False,
    dedupe_fields: Tuple[str, ...] = ("group", "victim", "domain"),
) -> None:
    data = await _fetch_group_victims(group_name)

    if not data:
        return

    if save_file:
        filename = f"{group_name}_victims.json"
        with open(filename, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        print(f"Saved ransomware.live data to {os.path.abspath(filename)}")

    if isinstance(data, dict):
        docs = [data]
    else:
        docs = [doc for doc in data if isinstance(doc, dict)]

    if not docs:
        return

    uniques = set()
    new_docs: List[Dict[str, Any]] = []

    for doc in docs:
        key_values = tuple((field, doc.get(field)) for field in dedupe_fields if doc.get(field) is not None)
        if not key_values:
            key = hash(json.dumps(doc, sort_keys=True))
        else:
            key = tuple(key_values)

        if key in uniques:
            continue

        filter_query = {field: doc.get(field) for field in dedupe_fields if doc.get(field) is not None}
        if filter_query:
            existing = await collection.find_one(filter_query)
            if existing:
                continue

        new_docs.append(doc)
        uniques.add(key)

    if new_docs:
        await collection.insert_many(new_docs)
        print(f"Inserted {len(new_docs)} ransomware.live victims for group '{group_name}' into {collection.name}")


async def _fetch_group_victims(group_name: str) -> Any:
    base_url = "https://api.ransomware.live/v2/groupvictims"
    url = f"{base_url}/{group_name}"
    loop = asyncio.get_running_loop()

    def _request():
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        return response.json()

    return await loop.run_in_executor(None, _request)


async def _best_group_name(target: str, collection, field: str) -> str:
    try:
        names = await collection.distinct(field)
    except Exception:  # pylint: disable=broad-except
        names = []

    target_norm = _norm_text(target) or target
    best_name = target
    best_score = -1.0

    for name in names:
        if not name:
            continue
        score = _soft_ratio(target_norm, _norm_text(name))
        if score > best_score:
            best_score = score
            best_name = name

    return best_name
