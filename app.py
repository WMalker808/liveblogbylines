import os
from flask import Flask, render_template, request, jsonify
import requests
from datetime import datetime, timedelta
from collections import defaultdict

app = Flask(__name__)

# Set the GUARDIAN_API_KEY environment variable in your Render dashboard.
GUARDIAN_API_KEY = os.environ.get("GUARDIAN_API_KEY", "")

CAPI_BASE = "https://content.guardianapis.com"
MAX_PAGES = 20  # Safety cap to avoid runaway pagination


def fetch_live_blogs(api_key, from_date, to_date):
    """Fetch all live blogs in the given date range, paginating through results."""
    all_blogs = []
    page = 1

    while True:
        params = {
            "api-key": api_key,
            "type": "liveblog",
            "from-date": from_date,
            "to-date": to_date,
            "show-blocks": "body",
            "page-size": 50,
            "page": page,
            "order-by": "newest",
        }

        resp = requests.get(f"{CAPI_BASE}/search", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        response = data.get("response", {})
        status = response.get("status")
        if status != "ok":
            raise ValueError(f"CAPI returned status: {status}")

        results = response.get("results", [])
        total_pages = response.get("pages", 1)

        all_blogs.extend(results)

        if page >= total_pages or page >= MAX_PAGES:
            break
        page += 1

    return all_blogs


def analyze_blogs(blogs):
    """
    Count block-level bylines per blog and aggregate by day.

    A block-level byline is present when a block has a non-empty
    'contributors' list — i.e., an author is attributed to that
    specific block rather than to the article as a whole.
    """
    blog_data = []
    daily_counts = defaultdict(int)

    for blog in blogs:
        blocks = blog.get("blocks", {}).get("body", [])

        bylined_block_count = sum(
            1 for block in blocks if block.get("contributors")
        )

        pub_date = blog.get("webPublicationDate", "")[:10]

        blog_data.append(
            {
                "id": blog.get("id", ""),
                "title": blog.get("webTitle", "Untitled"),
                "url": blog.get("webUrl", ""),
                "date": pub_date,
                "total_blocks": len(blocks),
                "bylined_block_count": bylined_block_count,
            }
        )

        daily_counts[pub_date] += bylined_block_count

    blog_data.sort(key=lambda x: x["bylined_block_count"], reverse=True)
    sorted_daily = sorted(daily_counts.items())

    return blog_data, sorted_daily


@app.route("/")
def index():
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    return render_template("index.html", default_from=week_ago, default_to=today)


@app.route("/fetch", methods=["POST"])
def fetch():
    data = request.get_json()
    api_key = GUARDIAN_API_KEY
    from_date = data.get("from_date", "")
    to_date = data.get("to_date", "")

    if not from_date or not to_date:
        return jsonify({"success": False, "error": "Please supply both dates."})

    try:
        blogs = fetch_live_blogs(api_key, from_date, to_date)
        blog_data, sorted_daily = analyze_blogs(blogs)

        total_bylined = sum(b["bylined_block_count"] for b in blog_data)

        return jsonify(
            {
                "success": True,
                "blogs": blog_data,
                "daily_labels": [d[0] for d in sorted_daily],
                "daily_values": [d[1] for d in sorted_daily],
                "total_blogs_fetched": len(blog_data),
                "total_bylined_blocks": total_bylined,
            }
        )
    except requests.HTTPError as e:
        return jsonify({"success": False, "error": f"CAPI request failed: {e}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    app.run(debug=True)
