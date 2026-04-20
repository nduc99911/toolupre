import asyncio
import sqlite3
from app.services.facebook_api import FacebookAPI
from app import database as db

async def test():
    conn = sqlite3.connect('storage/reupmaster.db')
    conn.row_factory = sqlite3.Row
    pages = [dict(r) for r in conn.execute('SELECT * FROM fb_pages').fetchall()]
    
    results = []
    for page in pages:
        try:
            stats = await FacebookAPI.get_page_detailed_stats(page["page_id"], page["access_token"])
            if "error" not in stats:
                await db.save_page_stats({
                    "page_db_id": page["id"],
                    "fan_count": stats.get("fan_count", 0),
                    "followers_count": stats.get("followers_count", 0),
                    "total_engagement": stats.get("total_engagement", 0),
                    "avg_engagement": stats.get("avg_engagement", 0),
                    "post_count_recent": stats.get("post_count", 0)
                })
                stats["page_db_id"] = page["id"]
                results.append(stats)
            else:
                print(f"Error in stats! {stats}")
        except Exception as e:
            print(f"Exception! {e}")
            
    print(f"Final Count of results: {len(results)}")

asyncio.run(test())
