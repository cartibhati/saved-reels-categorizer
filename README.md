# Saved reels

Personal local application for browsing, categorizing, reviewing, and exporting saved Instagram reels.

## Run command

To launch the web application, run:

```bash
streamlit run app.py
```

Open your browser at `http://localhost:8501`.

To run the pipeline scripts from the project root:
```bash
python src/parse.py
python src/discover.py
python src/classify.py
python src/evaluate.py
```
## View modes

### Browse
- Filter by category, year saved, post type, review status, fan edit status, and creator.
- Filter by keyword across captions, hashtags, and summaries.
- Dense table view with columns for category, summary, creator, saved date, confidence, and Instagram link.
- Pagination at 25 items per page.
- Edit categories for single posts or bulk select multiple posts to update categories.

### Review queue
- Ordered with weak-signal posts first (captions under 15 meaningful characters), followed by lowest confidence.
- Displays post caption, hashtags, and Instagram link on the left.
- Displays current category, category selectbox, and action buttons ("Confirm and next", "Skip", "Previous") on the right.
- Displays progress counter such as "12 of 140 posts".

### Stats
- Displays single row of summary figures for total posts, manually corrected count, and needs review count.
- Displays category distribution chart and table.

### Export
- Filter by category.
- Export CSV file or plain text link list (one URL per line).
