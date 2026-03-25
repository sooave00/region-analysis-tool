import math
import time
import urllib.parse
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="생활권 인구 분석", page_icon="🚗", layout="wide")

KAKAO_REST_KEY = st.secrets["KAKAO_REST_KEY"]

# -----------------------------
# 상태 초기화
# -----------------------------
if "selected_origin" not in st.session_state:
    st.session_state.selected_origin = None

if "search_results" not in st.session_state:
    st.session_state.search_results = None

if "result_df" not in st.session_state:
    st.session_state.result_df = None

# -----------------------------
# 데이터 로드
# -----------------------------
@st.cache_data
def load_data():
    base_dir = Path(__file__).resolve().parent.parent
    csv_path = base_dir / "data_clean" / "dong_master.csv"
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    numeric_cols = [
        "lat","lng","총인구수",
        "0_4세","5_9세","10_12세","13_15세","16_18세",
        "19_24세","25_34세","35_49세","50_64세","65세이상"
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df

# -----------------------------
# 거리 계산
# -----------------------------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

# -----------------------------
# 주소 검색 (여러 결과 반환)
# -----------------------------
def search_kakao(query):
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_KEY}"}

    r = requests.get(url, headers=headers, params={"query": query}, timeout=10)

    if r.status_code != 200:
        return []

    docs = r.json().get("documents", [])

    results = []
    for d in docs:
        results.append({
            "name": d.get("place_name"),
            "address": d.get("address_name"),
            "lat": float(d["y"]),
            "lng": float(d["x"])
        })

    return results

# -----------------------------
# 길찾기
# -----------------------------
def drive_seconds_kakao(origin_lng, origin_lat, dest_lng, dest_lat):
    url = "https://apis-navi.kakaomobility.com/v1/directions"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_KEY}"}

    params = {
        "origin": f"{origin_lng},{origin_lat}",
        "destination": f"{dest_lng},{dest_lat}",
        "priority": "TIME"
    }

    r = requests.get(url, headers=headers, params=params, timeout=10)

    if r.status_code != 200:
        return None, None

    routes = r.json().get("routes", [])
    if not routes:
        return None, None

    summary = routes[0].get("summary")
    if not summary:
        return None, None

    return summary.get("duration"), summary.get("distance")

# -----------------------------
# UI
# -----------------------------
st.title("🚗 생활권 인구 분석")

# -----------------------------
# 1. 주소 입력
# -----------------------------
query = st.text_input("주소 또는 장소명 입력", "보성아파트")

if st.button("🔍 위치 찾기"):
    results = search_kakao(query)

    if not results:
        st.warning("검색 결과가 없습니다.")
    else:
        st.session_state.search_results = results
        st.session_state.selected_origin = None

# -----------------------------
# 2. 주소 선택
# -----------------------------
if st.session_state.search_results:

    st.write("📍 찾으시는 위치가 맞는지 선택해주세요.")

    options = [
        f"{r['name']} / {r['address']}"
        for r in st.session_state.search_results
    ]

    selected = st.radio("검색 결과", options)

    selected_index = options.index(selected)
    st.session_state.selected_origin = st.session_state.search_results[selected_index]

# -----------------------------
# 3. 분석 실행
# -----------------------------
if st.session_state.selected_origin:

    st.success(f"선택된 위치: {st.session_state.selected_origin['address']}")

    n_min = st.number_input("차로 몇 분?", 1, 180, 30)

    if st.button("🚀 분석 실행"):

        progress = st.progress(0)
        status = st.empty()

        origin = st.session_state.selected_origin
        origin_lat = origin["lat"]
        origin_lng = origin["lng"]

        status.write("📂 데이터 불러오는 중...")
        progress.progress(20)

        df = load_data()
        df = df.dropna(subset=["lat","lng"]).copy()

        # ❗ NONE 제거 (핵심)
        df = df[df["행정동명_전체"].notna()]
        df = df[df["행정동명_전체"] != "None"]

        status.write("📏 거리 계산 중...")
        progress.progress(40)

        df["dist"] = df.apply(
            lambda r: haversine(origin_lat, origin_lng, r["lat"], r["lng"]), axis=1
        )

        candidates = df[df["dist"] <= 25].sort_values("dist")

        status.write(f"🚗 이동시간 계산 중 ({len(candidates)}개)")
        progress.progress(60)

        results = []
        limit_sec = n_min * 60

        for i, row in candidates.iterrows():

            dur, dist = drive_seconds_kakao(
                origin_lng, origin_lat, row["lng"], row["lat"]
            )

            if dur and dur <= limit_sec:
                results.append({
                    "행정동": row["행정동명_전체"],
                    "이동시간": round(dur/60,1),
                    "총인구": int(row["총인구수"]),
                    "0~4세": int(row["0_4세"]),
                    "5~9세": int(row["5_9세"]),
                    "10~12세": int(row["10_12세"]),
                    "13~15세": int(row["13_15세"]),
                    "16~18세": int(row["16_18세"]),
                    "19~24세": int(row["19_24세"]),
                    "25~34세": int(row["25_34세"]),
                    "35~49세": int(row["35_49세"]),
                    "50~64세": int(row["50_64세"]),
                    "65세이상": int(row["65세이상"])
                })

            progress.progress(min(60 + int(i/len(candidates)*40), 99))
            status.write(f"🚗 계산 중 {i+1}/{len(candidates)}")
            time.sleep(0.02)

        progress.progress(100)
        status.write("✅ 완료")

        result_df = pd.DataFrame(results)

        if result_df.empty:
            st.warning("결과 없음")
        else:
            st.write(f"총 {len(result_df)}개 행정동")
            st.dataframe(result_df, use_container_width=True)
