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
OUTPUT_PATH = PROJECT_ROOT / "config" / "categories.json"

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
    """Filter out generic hashtags from prompt construction."""
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

def sample_posts(conn: sqlite3.Connection, target_sample_size: int = 150) -> list:
    """Sample ~150 posts stratified by year + all collection posts with non-empty captions."""
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM reels")
    all_posts = [dict(row) for row in cursor.fetchall()]

    posts_by_year = {}
    for p in all_posts:
        yr = p["saved_at"][:4] if p["saved_at"] else "Unknown"
        posts_by_year.setdefault(yr, []).append(p)

    sample = []
    total_all = len(all_posts)
    random.seed(42)

    for yr, p_list in posts_by_year.items():
        quota = max(4, int((len(p_list) / total_all) * target_sample_size))
        sample.extend(random.sample(p_list, min(quota, len(p_list))))

    # Include ALL posts from existing collections with non-empty captions
    sample_urls = {p["url"] for p in sample}
    coll_posts = [p for p in all_posts if p["existing_collection"] and p["caption"] and p["caption"].strip()]

    for cp in coll_posts:
        if cp["url"] not in sample_urls:
            sample.append(cp)
            sample_urls.add(cp["url"])

    return sample

def call_gemini_with_retry(client: genai.Client, contents: str, config=None, candidate_models=None, max_retries=3) -> tuple[str, str]:
    if candidate_models is None:
        candidate_models = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"]

    last_err = None
    for model_name in candidate_models:
        for attempt in range(1, max_retries + 1):
            try:
                print(f"Calling Gemini API with model: {model_name} (Attempt {attempt})...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                if response and response.text:
                    return response.text, model_name
            except Exception as e:
                last_err = e
                err_str = str(e)
                print(f"[Attempt {attempt}/{max_retries}] Model {model_name} warning: {err_str[:120]}")
                if any(code in err_str for code in ["503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "timeout"]):
                    sleep_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                    time.sleep(sleep_time)
                else:
                    break
    raise RuntimeError(f"All Gemini candidate models failed. Last error: {last_err}")

def run_phase2():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database {DB_PATH} does not exist. Run parse.py first.")

    conn = sqlite3.connect(DB_PATH)
    sampled = sample_posts(conn)
    conn.close()

    # Concise item formatting
    sample_text_lines = []
    for idx, p in enumerate(sampled, 1):
        tags = []
        if p["hashtags"]:
            try:
                tags = json.loads(p["hashtags"])
            except Exception:
                pass
        filtered_tags = filter_hashtags(tags)
        
        cap = p["caption"].strip().replace("\n", " ") if p["caption"] else ""
        if len(cap) > 200:
            cap = cap[:200] + "..."

        coll_str = f" [Collection: {p['existing_collection']}]" if p["existing_collection"] else ""
        owner_str = f" [@{p['owner_username']}]" if p["owner_username"] else ""
        tags_str = f" [Tags: {', '.join(filtered_tags)}]" if filtered_tags else ""

        line = f"Item #{idx}: URL={p['url']}{coll_str}{owner_str}{tags_str} Caption=\"{cap}\""
        sample_text_lines.append(line)

    prompt_context = f"""
You are an expert content taxonomy architect. Analyze the following sample of {len(sample_text_lines)} Instagram posts/reels saved by a user between 2021 and 2026.

INITIAL TAXONOMY CANDIDATES (Refine and expand these into 12 to 20 precise categories):
- Work & AI tools
- Coding/Dev
- Career/Interview/Resume
- Sales & Business
- Fitness/Calisthenics
- Marvel/Avengers edits
- Other edits I like
- Movie & series recommendations
- Dance
- Dating/Flirting
- Humor/Memes
- Motivation
- Music
- Travel
- Other (Catch-all fallback)

IMPORTANT RULES:
1. Propose between 12 and 20 distinct, well-defined categories.
2. Provide a clear 1-line definition for each category.
3. Select 2-3 representative example URLs from the sample for each category.
4. Estimate the percentage share of the full dataset for each category (summing to 100%).
5. Creator usernames are a WEAK hint only—do NOT classify based on username alone; focus primarily on captions and hashtags.
6. Keep an 'Other' category as a fallback, but try to minimize its share.
7. Map each of the user's 12 existing collections (Sales, The dream, Presentation, resume, Typeshi, Calisthenics, LDR, 1D♥️, 👀, Avengers, RiZZ, Theme page) to the closest proposed category (or indicate if it needs its own category).

SAMPLED POSTS:
{ chr(10).join(sample_text_lines) }

Return JSON matching this exact structure:
{{
  "categories": [
    {{
      "name": "Category Name",
      "definition": "One line definition of what belongs here",
      "example_urls": ["url1", "url2"],
      "estimated_share_percent": 10.0
    }}
  ],
  "collection_mappings": [
    {{
      "collection_name": "Calisthenics",
      "mapped_category": "Fitness/Calisthenics",
      "notes": "Direct 1:1 match"
    }}
  ]
}}
"""

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in .env file.")

    client = genai.Client(api_key=api_key)
    
    response_text, model_used = call_gemini_with_retry(
        client=client,
        contents=prompt_context,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2
        )
    )

    result_json = json.loads(response_text)

    # Calculate 'Other' share check
    other_share = 0.0
    for cat in result_json.get("categories", []):
        if cat.get("name", "").lower() in ["other", "unclear", "misc"]:
            other_share = cat.get("estimated_share_percent", 0.0)

    # Save to categories.json
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result_json, f, indent=2, ensure_ascii=False)

    return result_json, len(sample_text_lines), other_share, model_used

if __name__ == "__main__":
    result, sample_len, other_share, model_used = run_phase2()
    print("=" * 70)
    print("PHASE 2 COMPLETE: CATEGORY DISCOVERY & TAXONOMY PROPOSAL")
    print(f"Sample Size : {sample_len} posts (Stratified across 2021-2026 + Collections)")
    print(f"Model Used  : {model_used}")
    print("=" * 70)
    
    print("\nPROPOSED CATEGORIES TAXONOMY:")
    for idx, cat in enumerate(result.get("categories", []), 1):
        print(f"{idx:2d}. {cat['name']:<30} [{cat['estimated_share_percent']}% share]")
        print(f"    Definition  : {cat['definition']}")
        print(f"    Examples    : {', '.join(cat.get('example_urls', [])[:2])}")
        print()

    print("\nCOLLECTION MAPPINGS (12 Hand-made Collections):")
    for cm in result.get("collection_mappings", []):
        print(f"  - {cm['collection_name']:<20} -> {cm['mapped_category']:<30} ({cm.get('notes', '')})")

    print("\n" + "=" * 70)
    if other_share > 10.0:
        print(f"⚠️ WARNING: 'Other' category share is estimated at {other_share}%, which exceeds 10%. Consider refining categories.")
    else:
        print(f"✅ 'Other' category share is {other_share}%, well within the <10% threshold.")
    print(f"Taxonomy saved to {OUTPUT_PATH.resolve()}")
    print("=" * 70)
