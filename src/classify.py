import json
import os
import random
import sqlite3
import time
import sys
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "db" / "reels.db"
CATEGORIES_PATH = PROJECT_ROOT / "config" / "categories.json"

STOPLIST = {
    "explore", "explorepage", "reels", "reelsinstagram", "fyp", 
    "foryou", "foryoupage", "viral", "trending", "trendingreels", 
    "instagram", "instagood", "reel"
}
RELATIONSHIP_TAGS = {
    "relationship", "couples", "couple", "dating", "ldr", 
    "romance", "marriage", "bf", "gf", "partner", "rizz"
}

def filter_hashtags(tags: list) -> list:
    if not tags:
        return []
    cleaned = [str(t).lower().strip('#').strip() for t in tags]
    has_relationship = any(t in RELATIONSHIP_TAGS for t in cleaned)
    filtered = []
    for raw, clean in zip(tags, cleaned):
        if clean in STOPLIST:
            continue
        if clean == "love" and not has_relationship:
            continue
        filtered.append(raw)
    return filtered

def call_gemini_with_retry(client: genai.Client, contents: str, config=None, candidate_models=None, max_retries=3):
    if candidate_models is None:
        candidate_models = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"]

    last_err = None
    for model_name in candidate_models:
        for attempt in range(1, max_retries + 1):
            try:
                # print(f"Calling Gemini API with model: {model_name} (Attempt {attempt})...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                if response and response.text:
                    # Validate JSON before returning
                    try:
                        json.loads(response.text)
                        return response.text, model_name
                    except json.JSONDecodeError as je:
                        last_err = je
                        print(f"JSON decode error on attempt {attempt}: {je}")
                        time.sleep(2)
                        continue
            except Exception as e:
                last_err = e
                err_str = str(e)
                print(f"[Attempt {attempt}/{max_retries}] Model {model_name} warning: {err_str[:120]}")
                if any(code in err_str for code in ["503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "timeout"]):
                    sleep_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                    time.sleep(sleep_time)
                else:
                    # Wait and retry for other exceptions anyway, as it could be a model hallucination issue
                    time.sleep(3)
    raise RuntimeError(f"All Gemini candidate models failed. Last error: {last_err}")

def get_taxonomy():
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

def get_few_shot_examples(conn, taxonomy_data):
    cursor = conn.cursor()
    # Find valid collections mapped to categories
    valid_mappings = {}
    for mapping in taxonomy_data.get("collection_mappings", []):
        if mapping.get("status") != "unconfirmed":
            valid_mappings[mapping["collection_name"]] = mapping["mapped_category"]
    
    examples = []
    for coll_name, cat_name in valid_mappings.items():
        cursor.execute("SELECT * FROM reels WHERE existing_collection = ? AND caption != '' LIMIT 1", (coll_name,))
        row = cursor.fetchone()
        if row:
            p = dict(row)
            tags = []
            if p["hashtags"]:
                try: tags = json.loads(p["hashtags"])
                except: pass
            filtered_tags = filter_hashtags(tags)
            tags_str = f" [Tags: {', '.join(filtered_tags)}]" if filtered_tags else ""
            cap = p["caption"].strip().replace('\n', ' ') if p["caption"] else ""
            if len(cap) > 200: cap = cap[:200] + "..."
            examples.append({
                "caption": cap,
                "tags": tags_str,
                "expected_category": cat_name
            })
    return examples

def run_phase3():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    taxonomy_data = get_taxonomy()
    categories = taxonomy_data["categories"]
    few_shots = get_few_shot_examples(conn, taxonomy_data)
    
    cat_definitions = ""
    for c in categories:
        cat_definitions += f"- **{c['name']}**: {c['definition']}\n"
        if c.get("include"): cat_definitions += f"  Include: {', '.join(c['include'])}\n"
        if c.get("exclude"): cat_definitions += f"  Exclude: {', '.join(c['exclude'])}\n"

    few_shot_text = ""
    for ex in few_shots:
        few_shot_text += f"Caption: \"{ex['caption']}\"{ex['tags']} -> Category: \"{ex['expected_category']}\"\n"

    # Fetch unclassified posts
    cursor.execute("SELECT * FROM reels WHERE category IS NULL")
    unclassified = [dict(r) for r in cursor.fetchall()]
    total = len(unclassified)
    print(f"Total unclassified posts: {total}")
    
    if total == 0:
        print("All posts classified!")
        return

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    batch_size = 30
    processed = 0

    for i in range(0, total, batch_size):
        batch = unclassified[i:i+batch_size]
        batch_text = []
        for p in batch:
            tags = []
            if p["hashtags"]:
                try: tags = json.loads(p["hashtags"])
                except: pass
            filtered_tags = filter_hashtags(tags)
            tags_str = f" [Tags: {', '.join(filtered_tags)}]" if filtered_tags else ""
            cap = p["caption"].strip().replace('\n', ' ') if p["caption"] else ""
            if len(cap) > 250: cap = cap[:250] + "..."
            batch_text.append(f"ID: {p['id']} | Caption: \"{cap}\"{tags_str}")

        prompt = f"""
You are an expert Instagram content classifier. Classify the following {len(batch)} posts into the exact categories provided.

TAXONOMY (Must use exactly one of these names for 'category'):
{cat_definitions}

FEW-SHOT EXAMPLES:
{few_shot_text}

POSTS TO CLASSIFY:
{chr(10).join(batch_text)}

INSTRUCTIONS:
For each post, determine the best 'category' from the taxonomy. 
You may provide a 'secondary_category' if another fits well (or null).
'confidence' should be between 0.0 and 1.0.
'summary' should be a 1-sentence description of the post based on caption and tags.
'needs_review' should be 1 if you are very unsure (confidence < 0.6) or if it's placed in Other, else 0.

RETURN JSON FORMAT EXACTLY:
{{
  "results": [
    {{
      "id": "post_id_here",
      "category": "Category Name",
      "secondary_category": "Secondary Name or null",
      "confidence": 0.9,
      "summary": "Brief summary",
      "needs_review": 0
    }}
  ]
}}
"""
        # Call Gemini
        print(f"Processing batch {i//batch_size + 1}/{(total+batch_size-1)//batch_size}...")
        try:
            resp_text, _ = call_gemini_with_retry(
                client=client,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            result_json = json.loads(resp_text)
            
            # Update DB
            for res in result_json.get("results", []):
                cursor.execute('''
                    UPDATE reels 
                    SET category = ?, secondary_category = ?, confidence = ?, summary = ?, needs_review = ?
                    WHERE id = ?
                ''', (
                    res.get("category"),
                    res.get("secondary_category"),
                    res.get("confidence", 0.0),
                    res.get("summary", ""),
                    res.get("needs_review", 0),
                    res.get("id")
                ))
            conn.commit()
            processed += len(batch)
            print(f"Successfully processed {processed}/{total}")
        except Exception as e:
            print(f"Error processing batch: {e}")
            print("Retrying batch with smaller chunks or skipping...")
            time.sleep(5)
            continue # Skip to next batch on fatal error, don't stop the whole script
            
    conn.close()

if __name__ == "__main__":
    print("=" * 60)
    print("STARTING PHASE 3: BATCH CLASSIFICATION")
    print("=" * 60)
    run_phase3()
    print("=" * 60)
    print("PHASE 3 COMPLETE")
    print("=" * 60)
