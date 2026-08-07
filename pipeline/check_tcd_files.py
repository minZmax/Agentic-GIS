import os

folder = "data/raw/tcn/DATA_20260413"  
targets = {
    "route": "ROUTE_",
    "sttn": "STTN_",
    "routesttn": "ROUTESTTN_",
    "dwtcn": "DWTCN_",
}

for key, prefix in targets.items():
    matches = [f for f in os.listdir(folder) if f.upper().startswith(prefix) and f.lower().endswith(".dat")]
    if not matches:
        print(f"[{key}] 못 찾음")
        continue

    file_path = os.path.join(folder, matches[0])
    size_mb = round(os.path.getsize(file_path) / (1024**2), 2)
    print(f"\n=== {key} ({matches[0]}, {size_mb} MB) ===")

    for enc in ["cp949", "utf-8"]:
        try:
            with open(file_path, "r", encoding=enc) as f:
                lines = [f.readline() for _ in range(3)]
            print(f"인코딩: {enc}")
            for line in lines:
                print(repr(line))
            break
        except UnicodeDecodeError:
            print(f"{enc} 실패")
            continue