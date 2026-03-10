#Stramlit 실행 파일

import streamlit as st
import pandas as pd
import requests
import math
import time
import urllib.parse

# -----------------------------
# 카카오 API 키
# -----------------------------
KAKAO_REST_KEY = st.secrets["KAKAO_REST_KEY"]

# -----------------------------
# 데이터 로드
# -----------------------------
from pathlib import Path

@st.cache_data
def load_data():
    base_dir = Path(__file__).resolve().parent.parent
    csv_path = base_dir / "data_clean" / "dong_master.csv"
    return pd.read_csv(csv_path, encoding="utf-8-sig")

# -----------------------------
# 직선거리 계산
# -----------------------------
def haversine(lat1, lon1, lat2, lon2):

    R = 6371

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    return R * c


# -----------------------------
# 주소 → 좌표
# -----------------------------
def geocode_kakao(query):
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_KEY}"}
    full_url = f"{url}?query={urllib.parse.quote(query)}"

    r = requests.get(full_url, headers=headers, timeout=10)

    # 에러 원인 확인용
    if r.status_code != 200:
        st.error(f"카카오 주소검색 API 오류: status={r.status_code}")
        st.code(r.text[:500])
        return None

    data = r.json()
    docs = data.get("documents", [])

    if not docs:
        # 주소검색 실패 시, 키워드 검색 fallback
        kw_url = "https://dapi.kakao.com/v2/local/search/keyword.json"
        kw_full_url = f"{kw_url}?query={urllib.parse.quote(query)}"
        r2 = requests.get(kw_full_url, headers=headers, timeout=10)

        if r2.status_code != 200:
            st.error(f"카카오 키워드검색 API 오류: status={r2.status_code}")
            st.code(r2.text[:500])
            return None

        data2 = r2.json()
        docs2 = data2.get("documents", [])

        if not docs2:
            return None

        d0 = docs2[0]
        return {
            "lat": float(d0["y"]),
            "lng": float(d0["x"]),
            "address_name": d0.get("address_name", d0.get("place_name", query))
        }

    d0 = docs[0]
    return {
        "lat": float(d0["y"]),
        "lng": float(d0["x"]),
        "address_name": d0["address_name"]
    }

# -----------------------------
# 카카오 길찾기
# -----------------------------
def drive_seconds_kakao(origin_lng, origin_lat, dest_lng, dest_lat):

    url = "https://apis-navi.kakaomobility.com/v1/directions"

    headers = {
        "Authorization": f"KakaoAK {KAKAO_REST_KEY}"
    }

    params = {
        "origin": f"{origin_lng},{origin_lat}",
        "destination": f"{dest_lng},{dest_lat}",
        "priority": "TIME"
    }

    r = requests.get(url, headers=headers, params=params, timeout=10)
    data = r.json()

    routes = data.get("routes", [])
    if not routes:
        return None, None

    route0 = routes[0]

    # summary가 없는 비정상 응답 방어
    summary = route0.get("summary")
    if summary is None:
        return None, None

    duration = summary.get("duration")
    distance = summary.get("distance")

    if duration is None or distance is None:
        return None, None

    return duration, distance

# -----------------------------
# Streamlit UI
# -----------------------------
st.title("🚗 생활권 인구 분석")

address = st.text_input("기준 주소", "와동동 1412")

n_min = st.number_input("차로 몇 분?", 1, 120, 30)

run = st.button("분석 실행")


if run:

    with st.spinner("분석 중..."):

        origin = geocode_kakao(address)

        if origin is None:
            st.error("주소를 찾을 수 없습니다.")
            st.stop()

        origin_lat = origin["lat"]
        origin_lng = origin["lng"]

        dong_master = load_data()

        dong_master = dong_master.dropna(subset=["lat", "lng"])

        dong_master["직선거리_km"] = dong_master.apply(
            lambda row: haversine(
                origin_lat,
                origin_lng,
                row["lat"],
                row["lng"]
            ),
            axis=1
        )

        candidates = dong_master[dong_master["직선거리_km"] <= 25]

        results = []

        limit_sec = n_min * 60

        for _, row in candidates.iterrows():

            dur, dist = drive_seconds_kakao(
                origin_lng,
                origin_lat,
                row["lng"],
                row["lat"]
            )

            if dur is None or dist is None:
                print("길찾기 실패:", row["행정동명_전체"])
                continue

            if dur <= limit_sec:

                results.append({
                    "행정동": row["행정동명_전체"],
                    "drive_min": round(dur/60,1),
                    "총인구수": row["총인구수"]
                })

            time.sleep(0.1)

        df = pd.DataFrame(results)

        st.subheader("분석 결과")

        st.metric("생활권 행정동", len(df))
        st.metric("총 인구", int(df["총인구수"].fillna(0).sum()))


        st.dataframe(df)

