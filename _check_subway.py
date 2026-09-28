import sys; sys.stdout.reconfigure(encoding='utf-8')
from tools.db_tool import execute_query

# 1. subway_stations table
print("=== subway_stations columns & sample ===")
print(execute_query('SELECT * FROM subway_stations LIMIT 5'))

# 2. What end stops with '역' look like vs actual subway stations
print("\n=== Current OD end stops with 역 from 탄현 ===")
sql = """
SELECT DISTINCT m2.bis_stop_name, s2.stop_name, s2.dong_name
FROM tcn_dwtcn_raw d
JOIN bis_tcn_stop_mapping m1 ON d.start_stop_id = m1.tcn_stop_id AND m1.confidence_level IN ('EXACT','HIGH','MEDIUM')
JOIN stop_admin_mapping s1 ON m1.bis_stop_id = s1.stop_id
JOIN bis_tcn_stop_mapping m2 ON d.end_stop_id = m2.tcn_stop_id AND m2.confidence_level IN ('EXACT','HIGH','MEDIUM')
JOIN stop_admin_mapping s2 ON m2.bis_stop_id = s2.stop_id
WHERE (s1.housing_district_name ILIKE '%탄현%' OR s1.dong_name ILIKE '%탄현%')
  AND (m2.bis_stop_name ILIKE '%역%' OR s2.stop_name ILIKE '%역%')
LIMIT 30
"""
print(execute_query(sql))

# 3. Check how many total OD records from 탄현 to ALL destinations
print("\n=== Total OD from 탄현 to subway-named stops ===")
sql2 = """
SELECT COUNT(*) as cnt FROM tcn_dwtcn_raw d
JOIN bis_tcn_stop_mapping m1 ON d.start_stop_id = m1.tcn_stop_id AND m1.confidence_level IN ('EXACT','HIGH','MEDIUM')
JOIN stop_admin_mapping s1 ON m1.bis_stop_id = s1.stop_id
WHERE (s1.housing_district_name ILIKE '%탄현%' OR s1.dong_name ILIKE '%탄현%')
"""
print(execute_query(sql2))

# 4. subway_stations names
print("\n=== Subway station names in Goyang area ===")
sql3 = """
SELECT "STN_KOR", "LINE_NM" FROM subway_stations
WHERE "ADDR" ILIKE '%고양%' OR "STN_KOR" IN ('대화','주엽','정발산','마두','백석','탄현','일산','풍산','화정','원당','삼송')
ORDER BY "LINE_NM", "STN_KOR"
"""
print(execute_query(sql3))
