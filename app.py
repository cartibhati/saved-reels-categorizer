import html
import json
import re
import sqlite3
import pandas as pd
import streamlit as st
from pathlib import Path

# Page configuration
st.set_page_config(
    page_title="Saved reels",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB_PATH = Path(__file__).parent / "db" / "reels.db"
CATEGORIES_PATH = Path(__file__).parent / "config" / "categories.json"

if "toast_msg" in st.session_state:
    st.toast(st.session_state.toast_msg)
    del st.session_state.toast_msg


STOPLIST = {
    "explore", "explorepage", "reels", "reelsinstagram", "fyp", 
    "foryou", "foryoupage", "viral", "trending", "trendingreels", 
    "instagram", "instagood", "reel", "love"
}

# Injected CSS for UI styling constraints
# - Font: Atkinson Hyperlegible
# - Max corner radius: 4px
# - Colors: Background #F5F6F7, Surface #FFFFFF, Ink #1B1F24, Muted #5B636B, Border #D9DDE1, Accent #1F4E8C
# - Status: Needs review #B26A00, Corrected #2E7D4F
# - No animations, transitions, or shadows
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400;1,700&display=swap');

    /* Global reset and font setup */
    html, body, [class*="css"], .stApp {
        font-family: 'Atkinson Hyperlegible', system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        font-size: 15px !important;
        color: #1B1F24 !important;
        background-color: #F5F6F7 !important;
        line-height: 1.5 !important;
        -webkit-font-smoothing: antialiased;
    }

    /* Disable all animations, transitions, and hover lifts */
    *, *::before, *::after {
        transition: none !important;
        animation: none !important;
        box-shadow: none !important;
        text-decoration-skip-ink: auto;
    }

    /* Hide Streamlit header branding and deploy button */
    header[data-testid="stHeader"] {
        display: none !important;
    }
    footer {
        display: none !important;
    }
    #MainMenu {
        visibility: hidden !important;
    }

    /* Main container layout */
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
        max-width: 1200px !important;
    }

    /* Typography */
    h1, h2, h3, h4, h5, h6 {
        font-family: 'Atkinson Hyperlegible', sans-serif !important;
        font-weight: 700 !important;
        color: #1B1F24 !important;
        margin-top: 0 !important;
        margin-bottom: 0.75rem !important;
        letter-spacing: normal !important;
        text-transform: none !important;
    }
    h1 { font-size: 1.6rem !important; }
    h2 { font-size: 1.3rem !important; }
    h3 { font-size: 1.1rem !important; }

    /* Muted text */
    .muted-text {
        color: #5B636B !important;
        font-size: 0.9rem !important;
    }

    /* Caption block */
    .caption-box {
        background-color: #FFFFFF !important;
        border: 1px solid #D9DDE1 !important;
        border-radius: 4px !important;
        padding: 1rem !important;
        max-width: 80ch !important;
        white-space: pre-wrap !important;
        margin-bottom: 0.75rem !important;
        font-size: 0.95rem !important;
        line-height: 1.5 !important;
    }

    /* Tabular numerals for counts and confidence values */
    .tabular-num {
        font-variant-numeric: tabular-nums !important;
    }

    /* Button styling - Rectangular with 4px corner radius */
    div.stButton > button {
        border-radius: 4px !important;
        border: 1px solid #D9DDE1 !important;
        background-color: #FFFFFF !important;
        color: #1B1F24 !important;
        font-weight: 600 !important;
        font-size: 0.9rem !important;
        padding: 0.4rem 1rem !important;
        height: auto !important;
        cursor: pointer !important;
        text-transform: none !important;
    }
    div.stButton > button:focus {
        outline: 2px solid #1F4E8C !important;
        outline-offset: 1px !important;
    }
    /* Primary action button styling */
    div.stButton > button[kind="primary"] {
        background-color: #1F4E8C !important;
        color: #FFFFFF !important;
        border-color: #1F4E8C !important;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: #163866 !important;
        color: #FFFFFF !important;
    }

    /* Form input elements */
    div[data-baseweb="select"] > div, input, textarea {
        border-radius: 4px !important;
        border-color: #D9DDE1 !important;
        background-color: #FFFFFF !important;
        color: #1B1F24 !important;
    }
    div[data-baseweb="select"] > div:focus-within {
        border-color: #1F4E8C !important;
    }

    /* Sidebar container styling */
    section[data-testid="stSidebar"] {
        background-color: #FFFFFF !important;
        border-right: 1px solid #D9DDE1 !important;
    }
    section[data-testid="stSidebar"] .block-container {
        padding-top: 1.5rem !important;
    }

    /* Stats row */
    .stats-row {
        display: flex !important;
        gap: 2rem !important;
        background-color: #FFFFFF !important;
        border: 1px solid #D9DDE1 !important;
        border-radius: 4px !important;
        padding: 1rem 1.5rem !important;
        margin-bottom: 1.5rem !important;
    }
    .stats-item {
        display: flex !important;
        flex-direction: column !important;
    }
    .stats-label {
        font-size: 0.85rem !important;
        color: #5B636B !important;
    }
    .stats-value {
        font-size: 1.5rem !important;
        font-weight: 700 !important;
        color: #1B1F24 !important;
        font-variant-numeric: tabular-nums !important;
    }
</style>
""", unsafe_allow_html=True)

@st.cache_data
def load_categories():
    if CATEGORIES_PATH.exists():
        with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [c["name"] for c in data.get("categories", [])]
    return []

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def is_weak_signal(caption: str, hashtags_json: str) -> bool:
    text = caption or ""
    text = re.sub(r'@[A-Za-z0-9_.]+', '', text)
    tags = []
    if hashtags_json:
        try:
            tags = json.loads(hashtags_json)
        except:
            pass
    
    valid_tags = [t for t in tags if str(t).lower().strip('#').strip() not in STOPLIST]
    words = [w for w in text.split() if w.lower().strip('#').strip() not in STOPLIST]
    cleaned = re.sub(r'[^\w\s]', '', " ".join(words)).strip()
    total_signal = cleaned + " ".join(valid_tags)
    return len(total_signal.strip()) < 15

categories_list = load_categories()

# Navigation Sidebar
st.sidebar.markdown("### Navigation")
mode = st.sidebar.radio(
    "Select view mode",
    ["Browse", "Review queue", "Stats", "Export"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")

# Main Title
st.title("Saved reels")

# MODE 1: BROWSE
if mode == "Browse":
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT DISTINCT strftime('%Y', saved_at) FROM reels WHERE saved_at IS NOT NULL ORDER BY 1 DESC")
    years = [r[0] for r in c.fetchall() if r[0]]

    c.execute("SELECT DISTINCT post_type FROM reels WHERE post_type IS NOT NULL")
    post_types = [r[0] for r in c.fetchall() if r[0]]

    c.execute("SELECT DISTINCT owner_username FROM reels WHERE owner_username IS NOT NULL AND owner_username != '' ORDER BY owner_username")
    creators = [r[0] for r in c.fetchall() if r[0]]

    conn.close()

    # Sidebar Filters
    st.sidebar.markdown("### Filters")
    selected_cat = st.sidebar.selectbox("Filter category", ["All"] + categories_list)
    selected_year = st.sidebar.selectbox("Filter year saved", ["All"] + years)
    selected_type = st.sidebar.selectbox("Filter post type", ["All"] + post_types)
    selected_nr = st.sidebar.selectbox("Filter review status", ["All", "Needs review", "Reviewed"])
    selected_edit = st.sidebar.selectbox("Filter fan edit status", ["All", "Fan edit", "Not fan edit"])
    selected_creator = st.sidebar.selectbox("Filter creator", ["All"] + creators[:200])

    search_query = st.text_input("Filter by keyword", "")

    # Build SQL Query
    query = "SELECT * FROM reels WHERE 1=1"
    params = []

    if selected_cat != "All":
        query += " AND category = ?"
        params.append(selected_cat)
    if selected_year != "All":
        query += " AND strftime('%Y', saved_at) = ?"
        params.append(selected_year)
    if selected_type != "All":
        query += " AND post_type = ?"
        params.append(selected_type)
    if selected_nr != "All":
        if selected_nr == "Needs review":
            query += " AND needs_review = 1"
        elif selected_nr == "Reviewed":
            query += " AND reviewed = 1"
    if selected_edit != "All":
        query += " AND is_edit = ?"
        params.append(1 if selected_edit == "Fan edit" else 0)
    if selected_creator != "All":
        query += " AND owner_username = ?"
        params.append(selected_creator)

    if search_query.strip():
        q = f"%{search_query.strip().lower()}%"
        query += " AND (LOWER(caption) LIKE ? OR LOWER(hashtags) LIKE ? OR LOWER(summary) LIKE ?)"
        params.extend([q, q, q])

    query += " ORDER BY saved_at DESC"

    conn = get_db()
    c = conn.cursor()
    c.execute(query, params)
    results = [dict(r) for r in c.fetchall()]
    conn.close()

    total_results = len(results)

    if total_results == 0:
        st.info("No posts match these filters. Clear a filter or change the search.")
    else:
        page_size = 25
        total_pages = (total_results + page_size - 1) // page_size

        col_pg1, col_pg2 = st.columns([1, 4])
        with col_pg1:
            page = st.number_input("Page number", min_value=1, max_value=total_pages, value=1, step=1, label_visibility="collapsed")

        start_idx = (page - 1) * page_size
        end_idx = min(start_idx + page_size, total_results)

        st.markdown(f"<p class='muted-text tabular-num'>Showing {start_idx + 1} to {end_idx} of {total_results} matching posts</p>", unsafe_allow_html=True)
        page_items = results[start_idx:end_idx]

        # Table data preparation
        table_rows = []
        for p in page_items:
            conf_val = f"{int((p['confidence'] or 0) * 100)}%"
            saved_date = p["saved_at"][:10] if p["saved_at"] else "Unknown"
            creator = f"@{p['owner_username']}" if p["owner_username"] else "Unknown"
            summary_text = (p["summary"] or p["caption"] or "").replace("\n", " ").strip()
            if len(summary_text) > 100:
                summary_text = summary_text[:100] + "..."

            table_rows.append({
                "Select": False,
                "ID": p["id"],
                "Category": p["category"] or "Unclassified",
                "Summary": summary_text,
                "Creator": creator,
                "Saved": saved_date,
                "Confidence": conf_val,
                "Status": "Needs review" if p["needs_review"] else ("Corrected" if p.get("manually_corrected") else "Assigned"),
                "URL": p["url"]
            })

        df_table = pd.DataFrame(table_rows)

        # Dense data editor/table
        edited_df = st.data_editor(
            df_table,
            column_config={
                "Select": st.column_config.CheckboxColumn("Select", default=False),
                "URL": st.column_config.LinkColumn("Open post"),
                "Confidence": st.column_config.TextColumn("Confidence")
            },
            disabled=["ID", "Category", "Summary", "Creator", "Saved", "Confidence", "Status", "URL"],
            hide_index=True,
            width="stretch",
            key="browse_table"
        )

        # Inline Single Post Edit & Bulk Edit Section
        selected_ids = edited_df[edited_df["Select"]]["ID"].tolist()

        st.markdown("---")
        
        # Undo button logic for Browse
        conn_undo = get_db()
        c_undo = conn_undo.cursor()
        c_undo.execute("SELECT * FROM corrections ORDER BY id DESC LIMIT 1")
        last_corr = c_undo.fetchone()
        
        col_title, col_undo = st.columns([3, 1])
        with col_title:
            st.markdown("### Edit category")
        with col_undo:
            if last_corr:
                if st.button("Undo last change", key="undo_browse"):
                    old_nr = last_corr["old_needs_review"] if last_corr["old_needs_review"] is not None else 1
                    old_rev = last_corr["old_reviewed"] if last_corr["old_reviewed"] is not None else 0
                    old_mc = last_corr["old_manually_corrected"] if last_corr["old_manually_corrected"] is not None else 0
                    c_undo.execute("UPDATE reels SET category = ?, manually_corrected = ?, needs_review = ?, reviewed = ? WHERE id = ?", (last_corr["old_category"], old_mc, old_nr, old_rev, last_corr["post_id"]))
                    c_undo.execute("DELETE FROM corrections WHERE id = ?", (last_corr["id"],))
                    conn_undo.commit()
                    st.toast("Last change undone!")
                    st.rerun()
        conn_undo.close()
        
        col_ed1, col_ed2 = st.columns([3, 1])
        with col_ed1:
            target_cat = st.selectbox("Select new category", categories_list, key="bulk_target_cat")
        with col_ed2:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            if st.button("Apply category to selected posts", type="primary", disabled=len(selected_ids) == 0):
                conn_b = get_db()
                c_b = conn_b.cursor()
                for pid in selected_ids:
                    # Get old state for correction log
                    c_b.execute("SELECT category, needs_review, reviewed, manually_corrected FROM reels WHERE id = ?", (pid,))
                    old_row = c_b.fetchone()
                    c_b.execute("INSERT INTO corrections (post_id, old_category, new_category, timestamp, old_needs_review, old_reviewed, old_manually_corrected) VALUES (?, ?, ?, datetime('now'), ?, ?, ?)", (pid, old_row["category"], target_cat, old_row["needs_review"], old_row["reviewed"], old_row["manually_corrected"]))
                    c_b.execute("UPDATE reels SET category = ?, manually_corrected = 1, needs_review = 0, reviewed = 1 WHERE id = ?", (target_cat, pid))
                conn_b.commit()
                conn_b.close()
                st.session_state.toast_msg = f"Categories updated for {len(selected_ids)} selected posts."
                st.rerun()

        # Single Post Edit Helper
        with st.expander("Edit category for single post by ID"):
            col_s1, col_s2, col_s3 = st.columns([2, 3, 2])
            with col_s1:
                single_id = st.text_input("Post ID", "")
            with col_s2:
                single_cat = st.selectbox("New category", categories_list, key="single_cat_sel")
            with col_s3:
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button("Save category", key="save_single_cat_btn"):
                    if single_id.strip():
                        conn_s = get_db()
                        c_s = conn_s.cursor()
                        c_s.execute("SELECT category, needs_review, reviewed, manually_corrected FROM reels WHERE id = ?", (single_id.strip(),))
                        old_row = c_s.fetchone()
                        if old_row:
                            c_s.execute("INSERT INTO corrections (post_id, old_category, new_category, timestamp, old_needs_review, old_reviewed, old_manually_corrected) VALUES (?, ?, ?, datetime('now'), ?, ?, ?)", (single_id.strip(), old_row["category"], single_cat, old_row["needs_review"], old_row["reviewed"], old_row["manually_corrected"]))
                        c_s.execute("UPDATE reels SET category = ?, manually_corrected = 1, needs_review = 0, reviewed = 1 WHERE id = ?", (single_cat, single_id.strip()))
                        conn_s.commit()
                        conn_s.close()
                        st.session_state.toast_msg = "Category updated."
                        st.rerun()

# MODE 2: REVIEW QUEUE
elif mode == "Review queue":
    st.markdown("## Review queue")

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM reels WHERE manually_corrected = 0 OR manually_corrected IS NULL")
    all_uncorrected = [dict(r) for r in c.fetchall()]
    conn.close()

    queue_posts = []
    for p in all_uncorrected:
        conf = p["confidence"] or 0.0
        if p.get("needs_review") == 1 or conf < 0.6 or is_weak_signal(p["caption"], p["hashtags"]):
            queue_posts.append(p)

    # Sort queue: weak signal posts first, then lowest confidence
    queue_posts.sort(key=lambda p: (not is_weak_signal(p["caption"], p["hashtags"]), p["confidence"] or 0.0))

    if "queue_idx" not in st.session_state:
        st.session_state.queue_idx = 0

    total_queue = len(queue_posts)

    if total_queue == 0:
        st.success("No posts need review.")
    else:
        if st.session_state.queue_idx >= total_queue:
            st.session_state.queue_idx = 0

        curr_post = queue_posts[st.session_state.queue_idx]
        progress_pct = (st.session_state.queue_idx + 1) / total_queue

        # Counter and progress bar
        st.markdown(f"<p class='tabular-num' style='font-weight: 600; margin-bottom: 0.2rem;'>{st.session_state.queue_idx + 1} of {total_queue} posts</p>", unsafe_allow_html=True)
        st.progress(progress_pct)

        col_left, col_right = st.columns([3, 2])

        tags = []
        if curr_post["hashtags"]:
            try:
                tags = json.loads(curr_post["hashtags"])
            except:
                pass

        cap = curr_post["caption"] or "No caption"
        cap_escaped = html.escape(cap)

        with col_left:
            st.markdown("### Post content")
            st.markdown(f"<div class='caption-box'>{cap_escaped}</div>", unsafe_allow_html=True)
            if tags:
                tags_escaped = html.escape(', '.join(tags))
                st.markdown(f"<p class='muted-text'>Hashtags: {tags_escaped}</p>", unsafe_allow_html=True)
            st.markdown(f"<p><a href='{html.escape(curr_post['url'])}' target='_blank' style='color: #1F4E8C; font-weight: 600;'>Open post on Instagram</a></p>", unsafe_allow_html=True)

        with col_right:
            st.markdown("### Category assignment")
            st.markdown(f"<p>Current category: <strong>{curr_post['category'] or 'Unclassified'}</strong></p>", unsafe_allow_html=True)
            
            new_cat_sel = st.selectbox(
                "New category",
                categories_list,
                index=categories_list.index(curr_post['category']) if curr_post['category'] in categories_list else 0,
                key=f"rq_sel_{curr_post['id']}"
            )

            st.markdown("<div style='height: 1rem;'></div>", unsafe_allow_html=True)
            
            if st.button("Confirm and next", type="primary", key=f"confirm_btn_{curr_post['id']}"):
                conn_r = get_db()
                c_r = conn_r.cursor()
                c_r.execute("INSERT INTO corrections (post_id, old_category, new_category, timestamp, old_needs_review, old_reviewed, old_manually_corrected) VALUES (?, ?, ?, datetime('now'), ?, ?, ?)", (curr_post['id'], curr_post['category'], new_cat_sel, curr_post.get('needs_review'), curr_post.get('reviewed'), curr_post.get('manually_corrected')))
                c_r.execute("UPDATE reels SET category = ?, manually_corrected = 1, needs_review = 0, reviewed = 1 WHERE id = ?", (new_cat_sel, curr_post['id']))
                conn_r.commit()
                conn_r.close()
                st.session_state.toast_msg = "Confirmed."
                # Don't increment index because the current post is removed from queue
                if st.session_state.queue_idx >= total_queue - 1:
                    st.session_state.queue_idx = max(0, total_queue - 2)
                st.rerun()

            col_sub1, col_sub2 = st.columns(2)
            with col_sub1:
                if st.button("Skip", key=f"skip_btn_{curr_post['id']}"):
                    st.session_state.queue_idx = (st.session_state.queue_idx + 1) % total_queue
                    st.rerun()
            with col_sub2:
                if st.button("Previous", key=f"prev_btn_{curr_post['id']}"):
                    st.session_state.queue_idx = (st.session_state.queue_idx - 1) % total_queue
                    st.rerun()
            
            # Undo in Review Queue
            conn_u = get_db()
            c_u = conn_u.cursor()
            last_corr = c_u.execute("SELECT * FROM corrections ORDER BY id DESC LIMIT 1").fetchone()
            if last_corr:
                st.markdown("<div style='height: 1rem;'></div>", unsafe_allow_html=True)
                if st.button("Undo last change", key=f"undo_btn_{curr_post['id']}"):
                    old_nr = last_corr["old_needs_review"] if last_corr["old_needs_review"] is not None else 1
                    old_rev = last_corr["old_reviewed"] if last_corr["old_reviewed"] is not None else 0
                    old_mc = last_corr["old_manually_corrected"] if last_corr["old_manually_corrected"] is not None else 0
                    c_u.execute("UPDATE reels SET category = ?, manually_corrected = ?, needs_review = ?, reviewed = ? WHERE id = ?", (last_corr["old_category"], old_mc, old_nr, old_rev, last_corr["post_id"]))
                    c_u.execute("DELETE FROM corrections WHERE id = ?", (last_corr["id"],))
                    conn_u.commit()
                    st.session_state.toast_msg = "Last change undone!"
                    # Decrement index or stay in bounds
                    st.rerun()
            conn_u.close()

# MODE 3: STATS
elif mode == "Stats":
    st.markdown("## Stats")

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM reels")
    total_reels = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM reels WHERE manually_corrected = 1")
    manual_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM reels WHERE needs_review = 1")
    review_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM reels WHERE reviewed = 1")
    reviewed_count = c.fetchone()[0]

    c.execute("SELECT category, COUNT(*) FROM reels GROUP BY category ORDER BY COUNT(*) DESC")
    cat_counts = dict(c.fetchall())

    conn.close()

    # Plain single row of figures at the top
    st.markdown(f"""
    <div class="stats-row">
        <div class="stats-item">
            <span class="stats-label">Total posts</span>
            <span class="stats-value">{total_reels}</span>
        </div>
        <div class="stats-item">
            <span class="stats-label">Reviewed</span>
            <span class="stats-value">{reviewed_count}</span>
        </div>
        <div class="stats-item">
            <span class="stats-label">Manually corrected</span>
            <span class="stats-value">{manual_count}</span>
        </div>
        <div class="stats-item">
            <span class="stats-label">Needs review</span>
            <span class="stats-value">{review_count}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### Category breakdown")

    df_stats = pd.DataFrame([
        {"Category": cat or "Unclassified", "Count": count, "Percentage": f"{(count/total_reels)*100:.2f}%"}
        for cat, count in cat_counts.items()
    ])

    st.bar_chart(df_stats.set_index("Category")["Count"], color="#1F4E8C")
    st.dataframe(df_stats, hide_index=True, use_container_width=True)

# MODE 4: EXPORT
elif mode == "Export":
    st.markdown("## Export")

    export_cat = st.selectbox("Filter by category to export", ["All categories"] + categories_list)

    conn = get_db()
    c = conn.cursor()

    if export_cat == "All categories":
        c.execute("SELECT * FROM reels ORDER BY category, saved_at DESC")
    else:
        c.execute("SELECT * FROM reels WHERE category = ? ORDER BY saved_at DESC", (export_cat,))

    exp_rows = [dict(r) for r in c.fetchall()]
    conn.close()

    st.markdown(f"<p class='muted-text tabular-num'>Found {len(exp_rows)} posts to export</p>", unsafe_allow_html=True)

    if exp_rows:
        df_exp = pd.DataFrame(exp_rows)
        url_text = "\n".join([r["url"] for r in exp_rows])

        col_ex1, col_ex2 = st.columns(2)

        with col_ex1:
            st.download_button(
                label="Export CSV",
                data=df_exp.to_csv(index=False, encoding="utf-8-sig"),
                file_name=f"reels_{export_cat.lower().replace(' ', '_')}.csv",
                mime="text/csv",
                type="primary"
            )

        with col_ex2:
            st.download_button(
                label="Export link list",
                data=url_text,
                file_name=f"links_{export_cat.lower().replace(' ', '_')}.txt",
                mime="text/plain"
            )

        st.markdown("---")
        st.markdown("### Link list preview")
        st.text_area("Link list text", value=url_text, height=200, label_visibility="collapsed")
