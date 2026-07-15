from typing import List, Tuple, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session

CATEGORY_NAME_MAP = {
    "tourist_spot": "관광지",
    "culture_facility": "문화시설",
    "festival": "축제·행사",
    "leports": "레포츠",
    "accommodation": "숙박",
    "shopping": "쇼핑",
}


def get_board_rankings(
    db: Session,
    sort: str,
    regions: List[str],
    categories: List[str],
    page: int,
    size: int,
) -> Tuple[List[Dict[str, Any]], int]:
    """Calculate and retrieve location rankings based on championship_rate or win_rate."""
    
    # 1. Base Query with Common Table Expressions (CTE) to aggregate match games
    query_str = """
    WITH game_sides AS (
      SELECT location_a_id AS location_id, winner_id, is_final FROM match_games WHERE winner_id IS NOT NULL
      UNION ALL
      SELECT location_b_id AS location_id, winner_id, is_final FROM match_games WHERE winner_id IS NOT NULL
    ),
    agg_stats AS (
      SELECT
        location_id,
        COUNT(*) AS total_games,
        SUM(CASE WHEN winner_id = location_id THEN 1 ELSE 0 END) AS total_wins,
        SUM(CASE WHEN is_final THEN 1 ELSE 0 END) AS final_appearances,
        SUM(CASE WHEN is_final AND winner_id = location_id THEN 1 ELSE 0 END) AS championships
      FROM game_sides
      GROUP BY location_id
      HAVING total_games >= 5
    )
    SELECT
      l.id AS location_id,
      l.title AS location_title,
      l.category AS location_category,
      l.first_image AS location_first_image,
      l.l_dong_signgu_cd AS location_region_code,
      a.total_games,
      a.total_wins,
      a.final_appearances,
      a.championships
    FROM agg_stats a
    JOIN locations l ON a.location_id = l.id
    """
    
    # 2. Add filters dynamically
    params = {}
    where_clauses = []
    
    # Region filtering: if regions list contains "ALL" or is empty, we don't filter.
    if regions and "ALL" not in regions:
        # Construct parameters like region_0, region_1, etc. to prevent SQL injection in IN clause
        region_placeholders = []
        for i, r in enumerate(regions):
            key = f"region_{i}"
            params[key] = r
            region_placeholders.append(f":{key}")
        where_clauses.append(f"l.l_dong_signgu_cd IN ({', '.join(region_placeholders)})")
        
    # Category filtering: if categories list contains "ALL" or is empty, we don't filter.
    if categories and "ALL" not in categories:
        category_placeholders = []
        for i, c in enumerate(categories):
            key = f"category_{i}"
            params[key] = c
            category_placeholders.append(f":{key}")
        where_clauses.append(f"l.category IN ({', '.join(category_placeholders)})")
        
    if where_clauses:
        query_str += " WHERE " + " AND ".join(where_clauses)
        
    # 3. Execute query
    result = db.execute(text(query_str), params).fetchall()
    
    # 4. Process aggregates in Python to easily handle division and tie-breakers
    processed_items = []
    for r in result:
        total_games = r.total_games
        total_wins = r.total_wins
        final_appearances = r.final_appearances
        championships = r.championships
        
        win_rate = total_wins / total_games if total_games > 0 else 0.0
        championship_rate = championships / final_appearances if final_appearances > 0 else 0.0
        
        # Check sort exclusion rule
        # A location with final_appearances == 0 is excluded when sorting by championship_rate
        if sort == "championship_rate" and final_appearances == 0:
            continue
            
        processed_items.append({
            "location_id": r.location_id,
            "title": r.location_title,
            "category": r.location_category,
            "category_name": CATEGORY_NAME_MAP.get(r.location_category, r.location_category),
            "first_image": r.location_first_image,
            "win_rate": round(win_rate, 4),
            "championship_rate": round(championship_rate, 4),
            "total_games": total_games,
            "total_wins": total_wins,
            "championships": championships,
            "final_appearances": final_appearances
        })
        
    # 5. Sort items according to rules
    if sort == "championship_rate":
        # Sort descending by championship_rate, then descending by championships, then ascending by title
        processed_items.sort(key=lambda x: (-x["championship_rate"], -x["championships"], x["title"]))
    else:
        # Sort descending by win_rate, then descending by total_wins, then ascending by title
        processed_items.sort(key=lambda x: (-x["win_rate"], -x["total_wins"], x["title"]))
        
    total = len(processed_items)
    
    # 6. Apply Rank (1-based index)
    for i, item in enumerate(processed_items):
        item["rank"] = i + 1
        
    # 7. Paginate
    offset = (page - 1) * size
    paginated_items = processed_items[offset : offset + size]
    
    # Shape items to conform to BoardRankingItem structure
    shaped_items = []
    for item in paginated_items:
        shaped_items.append({
            "rank": item["rank"],
            "location": {
                "id": item["location_id"],
                "title": item["title"],
                "category": item["category"],
                "category_name": item["category_name"],
                "first_image": item["first_image"]
            },
            "championship_rate": item["championship_rate"],
            "win_rate": item["win_rate"],
            "total_games": item["total_games"],
            "championships": item["championships"],
            "final_appearances": item["final_appearances"]
        })
        
    return shaped_items, total
