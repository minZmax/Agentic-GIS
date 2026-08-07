ROUTE_COLUMNS = [
    "op_date", "tcbo_id", "settle_region_cd", "route_id",
    "route_name", "route_no", "transport_type_cd",
    "route_distance", "route_stop_count",
]

STTN_COLUMNS = [
    "op_date", "tcbo_id", "settle_region_cd", "stop_id", "stop_name",
    "stop_ars_no", "stop_x", "stop_y", "sido_cd", "sido_name",
    "sigungu_cd", "sigungu_name", "dong_cd", "dong_name",
]

ROUTESTTN_COLUMNS = [
    "op_date", "tcbo_id", "settle_region_cd", "route_id", "route_name",
    "transport_type_cd", "stop_seq", "stop_id", "stop_name",
    "stop_x", "stop_y", "stop_ars_no", "route_cum_distance", "stop_distance",
]

def _build_dwtcn_columns():
    cols = ["op_date", "tcbo_id", "virtual_card_no", "transaction_id",
            "user_type_cd", "transfer_count"]
    groups = [
        "region", "settle_region", "operator", "transport_mode",
        "transport_type", "route", "vehicle", "trip_distance",
        "board_datetime", "board_stop_id", "alight_datetime", "alight_stop_id",
    ]
    for g in groups:
        for i in range(1, 11):
            cols.append(f"{g}_{i}")
    cols += [
        "start_board_datetime", "start_settle_region_cd", "start_transport_mode_cd",
        "start_transport_type_cd", "start_route_id", "start_stop_id", "start_fare",
        "end_alight_datetime", "end_settle_region_cd", "end_transport_mode_cd",
        "end_transport_type_cd", "end_route_id", "end_stop_id",
        "total_passenger_count", "total_fare", "total_distance",
        "total_ride_time", "total_trip_time",
    ]
    return cols

DWTCN_COLUMNS = _build_dwtcn_columns()

if __name__ == "__main__":
    print("ROUTE:", len(ROUTE_COLUMNS))
    print("STTN:", len(STTN_COLUMNS))
    print("ROUTESTTN:", len(ROUTESTTN_COLUMNS))
    print("DWTCN:", len(DWTCN_COLUMNS))  # 144 나와야 정상

CD_TFCMN_COLUMNS = ["tcbo_id", "transport_mode_cd", "transport_mode_name"]
CD_USERTYPE_COLUMNS = ["user_type_cd", "user_type_name"]
CD_CARDGB_COLUMNS = ["tcbo_id", "card_type_cd", "card_type_name"]
CD_TCBO_COLUMNS = ["tcbo_id", "tcbo_name"]