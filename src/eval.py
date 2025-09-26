import os
import re
from typing import Any, Dict, List, Optional
from datetime import datetime
from difflib import SequenceMatcher

from motor.motor_asyncio import AsyncIOMotorClient # type: ignore

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
    "discovered": ("discovered", "discovered")
}

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
) -> Dict[str, Any]:
    """
    Evaluate agent vs ransomware.live for a given group, with schema-aware normalization.
    Does global evaluation for all victimCompany values and per-victim company field comparison.
    """
    uri = os.getenv(mongo_uri_env)
    client = AsyncIOMotorClient(uri)

    live_coll = client[live_db_name][live_coll_name]
    agent_coll = client[agent_db_name][agent_coll_name]

    live_docs = await live_coll.find({
        "group": {"$regex": f"^{re.escape(group_name)}$", "$options": "i"}
    }).to_list(length=10000)
    agent_docs = await agent_coll.find({
        "ransomwareGroup": {"$regex": f"^{re.escape(group_name)}$", "$options": "i"}
    }).to_list(length=10000)

    result = {
        "group": group_name,
        "counts": {"live_docs": len(live_docs), "agent_docs": len(agent_docs)},
    }

    # --- Per victimCompany in agent collection: per-field eval ---
    detailed_per_victim = []
    unmatched_victims = []
    all_exact_scores = []
    all_soft_scores = []
    field_scores = {}  # Track scores by field

    for agent_doc in agent_docs:
        agent_company = _norm_text(agent_doc.get("victimCompany"))
        if not agent_company:
            continue
            
        live_matches = [ld for ld in live_docs if _norm_text(ld.get("victim")) == agent_company]
        if not live_matches:
            unmatched_victims.append(agent_company)
            continue
            
        live_doc = live_matches[0]
        per_field_victim, exacts_victim, softs_victim = [], [], []
        
        for canon, (live_k, agent_k) in FIELD_MAP.items():
            live_val = live_doc.get(live_k)
            agent_val = agent_doc.get(agent_k)
            
            if canon in ("victim", "group", "description"):
                ln = _norm_text(live_val)
                an = _norm_text(agent_val)
                exact = 1.0 if (ln and an and ln == an) else 0.0
                soft = _soft_ratio(ln, an)
            elif canon == "country":
                ln = _norm_text(live_val)
                an = _norm_text(agent_val)
                exact = 1.0 if (ln and an and ln == an) else 0.0
                soft = _soft_ratio(ln, an)
            elif canon == "domain":
                ln = _norm_domain(live_val)
                an = _norm_domain(agent_val)
                exact = 1.0 if (ln and an and ln == an) else 0.0
                soft = _soft_ratio(ln, an)
            elif canon in ("attack_date", "discovered"):
                if canon == "attack_date":
                    ld_val = _parse_dt(live_val, ATTACK_DATE_FORMATS)
                    ad_val = _parse_dt(agent_val, ATTACK_DATE_FORMATS)
                else:
                    ld_val = _parse_dt(live_val, DISCOVERED_FORMATS)
                    ad_val = _parse_dt(agent_val, DISCOVERED_FORMATS)
                exact = _date_equal_by_day(ld_val, ad_val)
                soft = exact
            else:
                ln = _norm_text(live_val)
                an = _norm_text(agent_val)
                exact = 1.0 if (ln and an and ln == an) else 0.0
                soft = _soft_ratio(ln, an)
            
            # Track field-specific scores
            if canon not in field_scores:
                field_scores[canon] = {"exact": [], "soft": []}
            field_scores[canon]["exact"].append(exact)
            field_scores[canon]["soft"].append(soft)
                
            per_field_victim.append({
                "field": canon,
                "live_value": live_val,
                "agent_value": agent_val,
                "exact": round(exact, 4),
                "soft": round(soft, 4),
            })
            exacts_victim.append(exact)
            softs_victim.append(soft)
        
        all_exact_scores.extend(exacts_victim)
        all_soft_scores.extend(softs_victim)
        
        detailed_per_victim.append({
            "victimCompany": agent_company,
            "scores": {
                "exact_accuracy": round(sum(exacts_victim)/len(exacts_victim), 4),
                "soft_similarity": round(sum(softs_victim)/len(softs_victim), 4),
            },
            "per_field": per_field_victim
        })

    # Calculate aggregate scores
    aggregate_exact_score = round(sum(all_exact_scores)/len(all_exact_scores), 4) if all_exact_scores else 0.0
    aggregate_soft_score = round(sum(all_soft_scores)/len(all_soft_scores), 4) if all_soft_scores else 0.0

    # Calculate per-field aggregate scores
    field_aggregate_scores = {}
    for field, scores in field_scores.items():
        exact_scores = scores["exact"]
        soft_scores = scores["soft"]
        field_aggregate_scores[field] = {
            "exact_accuracy": round(sum(exact_scores)/len(exact_scores), 4) if exact_scores else 0.0,
            "soft_similarity": round(sum(soft_scores)/len(soft_scores), 4) if soft_scores else 0.0,
            "sample_count": len(exact_scores)
        }

    result["detailed_per_victim"] = detailed_per_victim
    result["per_victim_match_count"] = len(detailed_per_victim)
    result["unmatched_victims"] = unmatched_victims
    result["unmatched_count"] = len(unmatched_victims)
    result["aggregate_scores"] = {
        "exact_accuracy": aggregate_exact_score,
        "soft_similarity": aggregate_soft_score,
    }
    result["field_aggregate_scores"] = field_aggregate_scores

    return result