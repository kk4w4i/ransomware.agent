import asyncio
from datetime import datetime
import json
import hashlib
from src.managers.llm_manager import LLMManager
from src.managers.vector_store_manager import VectorStoreManager
from src.utils.text_utils import clean_text

# -------- Chunking with 10% Overlap --------
def chunk_text(text, size):
    chunks = []
    step = int(size * 0.9)
    for start in range(0, len(text), step):
        chunk = text[start:start + size]
        if chunk:
            chunks.append(chunk)
        if start + size >= len(text):
            break
    return chunks

def fix_partial_json(s):
    """
    Attempts to salvage a broken/truncated JSON array by:
    - Truncating at the last complete object (find last '}')
    - Adding closing ] if missing.
    """
    # Remove everything after the last closing curly brace
    last_brace = s.rfind('}')
    if last_brace == -1:
        return None  # Nothing to extract
    repaired = s[:last_brace+1]
    # Try to wrap as list if it's supposed to be an array
    if repaired.strip().startswith('{'):
        repaired = '[' + repaired + ']'
    elif repaired.count('[') and not repaired.strip().endswith(']'):
        repaired += ']'
    return repaired

# -------- LLM Call now expects previous & next chunk context and returns a list --------
async def call_llm(prev_chunk, curr_chunk, next_chunk, llm: LLMManager):
    prompt = (
        f"""
        Given the current chunk of text and its surrounding context, 
        extract a list of valid entries. Return a JSON list; each entry should have: 
        'industry', 'attackDate', 'countryOfCompany', 'description', 'discovered', 'companyWebDomain', 'ransomwareGroup', 'victimCompany'
        PREVIOUS CHUNK:\n{prev_chunk if prev_chunk is not None else ''}\n\n
        CURRENT CHUNK:\n{curr_chunk}\n\n
        NEXT CHUNK:\n{next_chunk if next_chunk is not None else ''}\n\n

        --- OMISSIONS ---
            - Do NOT include any explanation, commentary, or formatting outside of the JSON list.
            - Return the output without any markdown formatting (no surrounding ```json blocks, white space).
        """
    )
    print("➡️ Calling LLM for current chunk...")
    result = await llm.get_formatted_json(prompt=prompt)
    print(" LLM response received, parsing entries...")
    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict):
            parsed = [parsed]
    except Exception:
        print("⚠️ LLM parsing failed, trying repair...")
        repaired = fix_partial_json(result)
        try:
            parsed = json.loads(repaired)
            print("✅ JSON repair successful!")
        except Exception as e:
            print("⚠️ JSON irrecoverably broken, chunk skipped.", e)
            parsed = []
    return parsed

# -------- Enhanced process_chunk with Vector Store Manager --------
async def process_chunk(i, chunks, llm: LLMManager, victims_collection, vector_store: VectorStoreManager, similarity_threshold: float = 0.85):
    """Process a chunk with vector similarity checking using Vector Store Manager"""
    curr_chunk = chunks[i]
    prev_chunk = chunks[i - 1] if i > 0 else None
    next_chunk = chunks[i + 1] if i < (len(chunks) - 1) else None

    print(f"\n--- Processing chunk {i+1}/{len(chunks)} ({len(curr_chunk)} chars) ---")
    chunk_entries = await call_llm(prev_chunk, curr_chunk, next_chunk, llm)
    
    results = []
    
    for entry_idx, entry in enumerate(chunk_entries):
        print(f"🔍 Processing entry {entry_idx + 1}/{len(chunk_entries)} from chunk {i+1}")
        
        # Use vector store manager to handle embedding and similarity check
        result = await vector_store.store_entry_with_embedding(
            collection=victims_collection,
            entry=entry,
            similarity_threshold=similarity_threshold
        )
        
        if result['stored']:
            print(f"✅ New entry stored: {entry.get('victimCompany', 'Unknown')}")
        else:
            similarity_score = result.get('similarity_score', 0)
            victim_company = result['entry'].get('victimCompany', 'Unknown')
            print(f"🔄 Using existing similar entry: {victim_company} (similarity: {similarity_score:.3f})")
        
        results.append(result['entry'])
    
    return results

# -------- Main Run Action (CONCURRENT) --------
async def run(page, victims_collection, sessions_collection, llm: LLMManager, hf_token: str, similarity_threshold: float = 0.85):
    """
    Main scraping function with vector store integration
    
    Args:
        page: Playwright page object
        victims_collection: MongoDB collection for victims
        sessions_collection: MongoDB collection for sessions
        llm: LLM Manager instance
        hf_token: Hugging Face API token
        similarity_threshold: Similarity threshold for duplicate detection (0.0-1.0)
    """
    print("🔎 Starting full page scrape with vector similarity detection!")
    
    # Initialize vector store manager
    async with VectorStoreManager(hf_token) as vector_store:
        # Setup vector index (runs once, safe to call multiple times)
        await vector_store.setup_vector_index(victims_collection)
        
        full_text = await page.content()
        full_text = await clean_text(full_text)
        print(f"📝 Grabbed {len(full_text)} characters of visible text.")

        # --- Session Hashing ---
        url = str(page.url)
        text_hash = hashlib.sha256(full_text.encode('utf-8')).hexdigest()

        existing = await sessions_collection.find_one({'url': url, 'text_hash': text_hash})
        if existing:
            print("⚠️ This page has already been scraped with the same content. Skipping.")
            return False

        # Store new session record
        session_record = {
            'url': url,
            'text_hash': text_hash,
            'timestamp': datetime.utcnow().isoformat()
        }
        await sessions_collection.insert_one(session_record)
        print("🗄️ Session recorded in DB.")

        max_length = llm.context_size * 2
        chunks = chunk_text(full_text, max_length // 3)
        print(f"🔀 Chopped into {len(chunks)} overlapping chunks.")

        # ----- Launch all LLM tasks concurrently with rate limiting -----
        # Use semaphore to limit concurrent processing and avoid API rate limits
        semaphore = asyncio.Semaphore(2)  # Process 2 chunks concurrently
        
        async def process_chunk_with_semaphore(i):
            async with semaphore:
                return await process_chunk(
                    i=i,
                    chunks=chunks,
                    llm=llm,
                    victims_collection=victims_collection,
                    vector_store=vector_store,
                    similarity_threshold=similarity_threshold
                )

        all_entries = await asyncio.gather(
            *[process_chunk_with_semaphore(i) for i in range(len(chunks))]
        )

        # Flatten results
        entries = [item for sublist in all_entries for item in sublist]
        
        # Count new vs existing entries
        total_entries = len(entries)
        
        print(f"\n✅ Scrape complete!")
        print(f"📊 Total entries processed: {total_entries}")
        print(f"🔍 Vector similarity threshold used: {similarity_threshold}")
        
        return True if entries else False