import math
import time
import urllib.parse
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="생활권 인구 분석", page_icon="🚗", layout="wide")

# -----------------------------
# 카카오 API 키
# -----------------------------
KAKAO_REST_KEY = st.secrets["KAKAO_REST_KEY"]

# -----------------------------
# 세션 상태 초기화
# -----------------------------
if "result_df" not in st.session_state:
    st.session_state.result_df = None

if "analysis_done" not in st.session_state:
    st.session_state.analysis_done = False

# -----------------------------
# 데이터 로드
# -----------------------------
@st.cache_data
def load_data():
    base_dir = Path(__file__).resolve().parent.parent
    csv_path = base_dir / "data_clean" / "dong_master.csv"
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

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
# UI
# -----------------------------
st.title("🚗 생활권 인구 분석")
st.caption("기준 주소에서 차로 이동 가능한 생활권 내 행정동과 연령별 인구를 표시합니다.")

col1, col2, col3 = st.columns([5, 2, 2])

with col1:
    address = st.text_input("기준 주소", "와동동 1412")

with col2:
    n_min = st.number_input("차로 몇 분?", min_value=1, max_value=180, value=30)

with col3:
    st.write("")
    run = st.button("분석 실행", use_container_width=True)
    reset = st.button("분석 초기화", use_container_width=True)

if reset:
    st.session_state.result_df = None
    st.session_state.analysis_done = False
    st.rerun()

# -----------------------------
# 분석 실행
# -----------------------------
if run:
    progress_bar = st.progress(0)
    status_text = st.empty()

    # 1. 주소 변환
    status_text.write("📍 주소를 좌표로 변환하는 중...")
    progress_bar.progress(10)

    origin = geocode_kakao(address)

    if origin is None:
        st.error("주소를 찾을 수 없습니다.")
        st.stop()

    origin_lat = origin["lat"]
    origin_lng = origin["lng"]

    # 2. 데이터 로딩
    status_text.write("📂 행정동 데이터를 불러오는 중...")
    progress_bar.progress(20)

    dong_master = load_data()
    dong_master = dong_master.dropna(subset=["lat", "lng"]).copy()

    # 3. 직선거리 계산
    status_text.write("📏 직선거리 계산 및 후보 정리 중...")
    progress_bar.progress(35)

    dong_master["직선거리_km"] = dong_master.apply(
        lambda row: haversine(origin_lat, origin_lng, row["lat"], row["lng"]),
        axis=1
    )

    # 기존 방식 유지: 25km 이내 후보
    candidates = dong_master[dong_master["직선거리_km"] <= 25].copy()
    candidates = candidates.sort_values("직선거리_km").reset_index(drop=True)

    # 4. 길찾기 계산
    total_candidates = len(candidates)
    status_text.write(f"🚗 이동시간 계산 중... (총 {total_candidates}개 후보)")
    progress_bar.progress(50)

    results = []
    limit_sec = n_min * 60

    if total_candidates == 0:
        status_text.write("⚠️ 후보 행정동이 없습니다.")
        progress_bar.progress(100)
        st.session_state.result_df = pd.DataFrame()
        st.session_state.analysis_done = True
    else:
        for i, row in candidates.iterrows():
            percent = int(50 + ((i + 1) / total_candidates) * 40)
            progress_bar.progress(percent)
            status_text.write(f"🚗 이동시간 계산 중... {i+1}/{total_candidates}")

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
                    "총인구수": int(row["총인구수"]) if pd.notna(row["총인구수"]) else 0,
                    "0~4세": int(row["0_4세"]) if pd.notna(row["0_4세"]) else 0,
                    "5~9세": int(row["5_9세"]) if pd.notna(row["5_9세"]) else 0,
                    "10~12세": int(row["10_12세"]) if pd.notna(row["10_12세"]) else 0,
                    "13~15세": int(row["13_15세"]) if pd.notna(row["13_15세"]) else 0,
                    "16~18세": int(row["16_18세"]) if pd.notna(row["16_18세"]) else 0,
                    "19~24세": int(row["19_24세"]) if pd.notna(row["19_24세"]) else 0,
                    "25~34세": int(row["25_34세"]) if pd.notna(row["25_34세"]) else 0,
                    "35~49세": int(row["35_49세"]) if pd.notna(row["35_49세"]) else 0,
                    "50~64세": int(row["50_64세"]) if pd.notna(row["50_64세"]) else 0,
                    "65세이상": int(row["65세이상"]) if pd.notna(row["65세이상"]) else 0
                })

            time.sleep(0.03)

        status_text.write("📊 결과 정리 중...")
        progress_bar.progress(95)

        result_df = pd.DataFrame(results)

        if not result_df.empty:
            result_df = result_df[
                [
                    "행정동", "이동시간(분)", "거리(km)", "총인구수",
                    "0~4세", "5~9세", "10~12세", "13~15세", "16~18세",
                    "19~24세", "25~34세", "35~49세", "50~64세", "65세이상"
                ]
            ].sort_values(["이동시간(분)", "총인구수"], ascending=[True, False]).reset_index(drop=True)

        st.session_state.result_df = result_df
        st.session_state.analysis_done = True

        progress_bar.progress(100)
        status_text.write("✅ 분석 완료")

# -----------------------------
# 결과 출력
# -----------------------------
if st.session_state.analysis_done:
    st.subheader("분석 결과")

    if st.session_state.result_df is None or st.session_state.result_df.empty:
        st.warning("해당 조건에서 생활권으로 포함되는 행정동이 없습니다.")
    else:
        result_df = st.session_state.result_df
        st.write(f"총 {len(result_df)}개 행정동 포함")
        st.dataframe(result_df, use_container_width=True)
