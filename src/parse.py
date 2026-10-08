import json
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_DIR = PROJECT_ROOT / "db"
DB_PATH = DB_DIR / "reels.db"

def fix_mojibake(text: str) -> str:
    """Repair latin-1 / utf-8 mojibake decoding artifacts."""
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text

def parse_item(item: dict, default_ts: int = 0, collection_name: str = None) -> dict:
    """Extract required normalized fields from a post JSON object."""
    fbid = item.get("fbid")
    ts = item.get("timestamp", default_ts)
    
    label_values = item.get("label_values", [])
    if not label_values and "dict" in item and isinstance(item["dict"], list):
        label_values = item["dict"]

    url = None
    caption = ""
    hashtags = []
    owner_username = ""
    owner_name = ""

    for lv in label_values:
        lbl = lv.get("label")
        title = lv.get("title")
        
        if lbl == "URL":
            url = lv.get("value") or lv.get("href")
        elif lbl == "Caption":
            caption = fix_mojibake(lv.get("value", ""))
        elif title == "Hashtags":
            for h_item in lv.get("dict", []):
                for sub_lv in h_item.get("dict", []):
                    if sub_lv.get("label") == "Name":
                        tag = fix_mojibake(sub_lv.get("value"))
                        if tag:
                            hashtags.append(tag.strip().lower())
        elif title == "Owner":
            for o_item in lv.get("dict", []):
                for sub_lv in o_item.get("dict", []):
                    if sub_lv.get("label") == "Username":
                        owner_username = fix_mojibake(sub_lv.get("value", ""))
                    elif sub_lv.get("label") == "Name":
                        owner_name = fix_mojibake(sub_lv.get("value", ""))

    if not url:
        return None

    post_type = "other"
    if "/reel/" in url:
        post_type = "reel"
    elif "/p/" in url:
        post_type = "post"
    elif "/tv/" in url:
        post_type = "tv"

    if ts and ts > 0:
        saved_at = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        saved_at = None

    if not fbid:
        match = re.search(r"/(reel|p|tv)/([^/]+)", url)
        fbid = match.group(2) if match else url

    return {
        "id": str(fbid),
        "url": url,
        "post_type": post_type,
        "caption": caption,
        "hashtags": json.dumps(hashtags, ensure_ascii=False),
        "owner_username": owner_username,
        "owner_name": owner_name,
        "saved_at": saved_at,
        "existing_collection": collection_name,
        "hashtags_list": hashtags
    }

def init_db(conn: sqlite3.Connection):
    """Create database tables and indices if not exist."""
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reels (
        id TEXT PRIMARY KEY,
        url TEXT UNIQUE,
        post_type TEXT,
        caption TEXT,
        hashtags TEXT,
        owner_username TEXT,
        owner_name TEXT,
        saved_at TEXT,
        existing_collection TEXT,
        category TEXT,
        secondary_category TEXT,
        confidence REAL,
        summary TEXT,
        needs_review INTEGER DEFAULT 0
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reels_url ON reels(url);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reels_category ON reels(category);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reels_needs_review ON reels(needs_review);")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS saved_music (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fbid TEXT,
        title TEXT,
        artist TEXT,
        saved_at TEXT,
        url TEXT
    )
    """)
    conn.commit()

def run_phase1():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # 1. Parse collections for mapping and extra items
    collections_file = DATA_DIR / "saved_collections.json"
    coll_map = {}
    coll_extra_items = []

    if collections_file.exists():
        with open(collections_file, "r", encoding="utf-8") as f:
            collections = json.load(f)
        for c in collections:
            c_name = None
            c_items = []
            c_ts = c.get("timestamp", 0)
            for lv in c.get("label_values", []):
                if lv.get("label") == "Name":
                    c_name = fix_mojibake(lv.get("value"))
                elif "dict" in lv:
                    c_items = lv["dict"]
            if c_name and c_items:
                for item in c_items:
                    parsed = parse_item(item, default_ts=c_ts, collection_name=c_name)
                    if parsed:
                        coll_map[parsed["url"]] = c_name
                        coll_extra_items.append(parsed)

    # 2. Parse main saved_posts.json
    posts_file = DATA_DIR / "saved_posts.json"
    all_posts_by_url = {}

    if posts_file.exists():
        with open(posts_file, "r", encoding="utf-8") as f:
            posts = json.load(f)
        for p in posts:
            parsed = parse_item(p)
            if parsed:
                url = parsed["url"]
                if url in coll_map:
                    parsed["existing_collection"] = coll_map[url]
                all_posts_by_url[url] = parsed

    # Add any collection post that wasn't in saved_posts.json
    for extra in coll_extra_items:
        if extra["url"] not in all_posts_by_url:
            all_posts_by_url[extra["url"]] = extra

    # Insert into SQLite reels table
    cursor = conn.cursor()
    for p in all_posts_by_url.values():
        cursor.execute("""
        INSERT INTO reels (
            id, url, post_type, caption, hashtags, owner_username, owner_name, saved_at, existing_collection
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            existing_collection = excluded.existing_collection,
            caption = excluded.caption,
            hashtags = excluded.hashtags,
            owner_username = excluded.owner_username,
            owner_name = excluded.owner_name,
            saved_at = excluded.saved_at
        """, (
            p["id"], p["url"], p["post_type"], p["caption"],
            p["hashtags"], p["owner_username"], p["owner_name"],
            p["saved_at"], p["existing_collection"]
        ))
    conn.commit()

    # 3. Parse saved_music.json
    music_file = DATA_DIR / "saved_music.json"
    if music_file.exists():
        cursor.execute("DELETE FROM saved_music")
        with open(music_file, "r", encoding="utf-8") as f:
            music = json.load(f)
        for item in music:
            fbid = item.get("fbid")
            ts = item.get("timestamp")
            saved_at = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None
            
            title = ""
            artist = ""
            url = ""
            for lv in item.get("label_values", []):
                lbl = lv.get("label")
                if lbl == "Title" and not title:
                    title = fix_mojibake(lv.get("value", ""))
                elif lbl == "Artist" and not artist:
                    artist = fix_mojibake(lv.get("value", ""))
                elif lbl == "URL" and not url:
                    url = lv.get("value") or lv.get("href")

            cursor.execute("""
            INSERT INTO saved_music (fbid, title, artist, saved_at, url)
            VALUES (?, ?, ?, ?, ?)
            """, (fbid, title, artist, saved_at, url))
        conn.commit()

    # Calculate statistics from database
    cursor.execute("SELECT COUNT(*) FROM reels")
    total_posts = cursor.fetchone()[0]

    cursor.execute("SELECT post_type, COUNT(*) FROM reels GROUP BY post_type")
    type_counts = dict(cursor.fetchall())

    cursor.execute("SELECT strftime('%Y', saved_at), COUNT(*) FROM reels GROUP BY strftime('%Y', saved_at) ORDER BY strftime('%Y', saved_at)")
    year_counts = dict(cursor.fetchall())

    cursor.execute("SELECT COUNT(*) FROM reels WHERE TRIM(caption) != ''")
    caption_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM reels WHERE existing_collection IS NOT NULL AND existing_collection != ''")
    in_collection_count = cursor.fetchone()[0]

    cursor.execute("SELECT hashtags, owner_username FROM reels")
    all_hashtags = []
    all_owners = []
    for h_json, owner in cursor.fetchall():
        if h_json:
            try:
                h_list = json.loads(h_json)
                all_hashtags.extend(h_list)
            except Exception:
                pass
        if owner and owner.strip():
            all_owners.append(owner.strip())

    top_hashtags = Counter(all_hashtags).most_common(15)
    top_owners = Counter(all_owners).most_common(15)

    conn.close()

    summary = {
        "total_posts": total_posts,
        "type_counts": type_counts,
        "year_counts": year_counts,
        "caption_count": caption_count,
        "caption_percentage": round((caption_count / total_posts * 100), 2) if total_posts else 0,
        "in_collection_count": in_collection_count,
        "top_hashtags": top_hashtags,
        "top_owners": top_owners
    }

    return summary

if __name__ == "__main__":
    summary = run_phase1()
    print("=" * 60)
    print("PHASE 1 COMPLETE: PARSE AND NORMALIZE SUMMARY")
    print("=" * 60)
    print(f"Total Unique Posts    : {summary['total_posts']}")
    print(f"Posts by Type         : {summary['type_counts']}")
    print(f"Posts by Year Saved   : {summary['year_counts']}")
    print(f"Posts with Caption    : {summary['caption_count']} ({summary['caption_percentage']}%)")
    print(f"Posts in Collections  : {summary['in_collection_count']}")
    print("\nTop 15 Most Frequent Hashtags:")
    for tag, count in summary['top_hashtags']:
        print(f"  #{tag:<20}: {count}")
    print("\nTop 15 Most Frequent Owners/Creators:")
    for owner, count in summary['top_owners']:
        print(f"  @{owner:<20}: {count}")
    print("=" * 60)
