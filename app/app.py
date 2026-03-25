# Streamlit 실행 파일

import streamlit as st
import pandas as pd
import requests
import math
import time
import urllib.parse
from pathlib import Path

# -----------------------------
# 페이지 기본 설정
# -----------------------------
st.set_page_config(page_title="생활권 인구 분석", page_icon="🚗", layout="wide")

# -----------------------------
# 카카오 API 키
# -----------------------------
KAKAO_REST_KEY = st.secrets["KAKAO_REST_KEY"]

# -----------------------------
# 데이터 로드
# -----------------------------
@st.cache_data
def load_data():
    base_dir = Path(__file__).resolve().parent.parent
    csv_path = base_dir / "data_clean" / "dong_master.csv"
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    # 숫자형 컬럼 보정
    numeric_cols = [
        "lat", "lng", "총인구수",
        "0_4세", "5_9세", "10_12세", "13_15세", "16_18세",
        "19_24세", "25_34세", "35_49세", "50_64세", "65세이상"
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df

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

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c

# -----------------------------
# 주소 → 좌표
# -----------------------------
def geocode_kakao(query):
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_KEY}"}
    full_url = f"{url}?query={urllib.parse.quote(query)}"

    r = requests.get(full_url, headers=headers, timeout=10)

    if r.status_code != 200:
        st.error(f"카카오 주소검색 API 오류: status={r.status_code}")
        st.code(r.text[:500])
        return None

    data = r.json()
    docs = data.get("documents", [])

    if not docs:
        # 주소검색 실패 시 키워드 검색 fallback
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

    if r.status_code != 200:
        return None, None

    data = r.json()
    routes = data.get("routes", [])

    if not routes:
        return None, None

    route0 = routes[0]
    summary = route0.get("summary")

    if summary is None:
        return None, None

    duration = summary.get("duration")
    distance = summary.get("distance")

    if duration is None or distance is None:
        return None, None

    return duration, distance

# -----------------------------
# 연령 그룹 설정
# -----------------------------
population_options = {
    "총인구": ["총인구수"],
    "영유아(0~9세)": ["0_4세", "5_9세"],
    "초중고(10~18세)": ["10_12세", "13_15세", "16_18세"],
    "청년층(19~34세)": ["19_24세", "25_34세"],
    "중장년층(35~64세)": ["35_49세", "50_64세"],
    "고령층(65세이상)": ["65세이상"]
}

# -----------------------------
# Streamlit UI
# -----------------------------
st.title("🚗 생활권 인구 분석")
st.caption("기준 주소에서 차로 이동 가능한 생활권 내 인구를 계산합니다.")

address = st.text_input("기준 주소", "와동동 1412")
n_min = st.number_input("차로 몇 분?", min_value=1, max_value=120, value=30)
selected_group = st.selectbox("분석 대상", list(population_options.keys()))

run = st.button("분석 실행", type="primary")

# -----------------------------
# 실행
# -----------------------------
if run:
    with st.spinner("분석 중..."):

        origin = geocode_kakao(address)

        if origin is None:
            st.error("주소를 찾을 수 없습니다.")
            st.stop()

        origin_lat = origin["lat"]
        origin_lng = origin["lng"]
        selected_cols = population_options[selected_group]

        dong_master = load_data()
        dong_master = dong_master.dropna(subset=["lat", "lng"]).copy()

        # 선택 연령대 합계 컬럼 만들기
        dong_master["선택인구"] = dong_master[selected_cols].fillna(0).sum(axis=1)

        # 직선거리 계산
        dong_master["직선거리_km"] = dong_master.apply(
            lambda row: haversine(
                origin_lat,
                origin_lng,
                row["lat"],
                row["lng"]
            ),
            axis=1
        )

        # 1차 후보군 추리기
        candidates = dong_master[dong_master["직선거리_km"] <= 25].copy()

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
                continue

            if dur <= limit_sec:
                results.append({
                    "행정동": row["행정동명_전체"],
                    "이동시간(분)": round(dur / 60, 1),
                    "거리(km)": round(dist / 1000, 1),
                    "인구수": int(row["선택인구"]) if pd.notna(row["선택인구"]) else 0
                })

            time.sleep(0.1)

        df = pd.DataFrame(results)

        st.subheader("분석 결과")
        st.write(f"기준 주소: **{origin['address_name']}**")

        if df.empty:
            st.warning("해당 조건에서 생활권으로 포함되는 행정동이 없습니다.")
            st.stop()

        total_pop = int(df["인구수"].fillna(0).sum())

        c1, c2 = st.columns(2)
        c1.metric("생활권 행정동 수", f"{len(df):,}개")
        c2.metric(f"{selected_group} 인구", f"{total_pop:,}명")

        df = df.sort_values(["이동시간(분)", "인구수"], ascending=[True, False]).reset_index(drop=True)

        st.dataframe(df, use_container_width=True)
