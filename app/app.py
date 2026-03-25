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
if "search_results" not in st.session_state:
    st.session_state.search_results = []

if "selected_origin" not in st.session_state:
    st.session_state.selected_origin = None

if "result_df" not in st.session_state:
    st.session_state.result_df = None

if "searched_query" not in st.session_state:
    st.session_state.searched_query = ""

# -----------------------------
# 광역시도 목록
# -----------------------------
SIDO_OPTIONS = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시",
    "대전광역시", "울산광역시", "세종특별자치시",
    "경기도", "강원특별자치도", "충청북도", "충청남도",
    "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도"
]

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
# 장소 검색
# -----------------------------
def search_kakao(query):
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_KEY}"}

    results = []

    # 1차: 키워드 검색
    keyword_url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    r1 = requests.get(
        keyword_url,
        headers=headers,
        params={"query": query, "size": 15},
        timeout=10
    )

    if r1.status_code == 200:
        docs = r1.json().get("documents", [])
        for d in docs:
            results.append({
                "name": d.get("place_name", ""),
                "address": d.get("address_name", ""),
                "road_address": d.get("road_address_name", ""),
                "lat": float(d["y"]),
                "lng": float(d["x"])
            })

    # 2차: 주소 검색도 보조로 추가
    address_url = "https://dapi.kakao.com/v2/local/search/address.json"
    r2 = requests.get(
        address_url,
        headers=headers,
        params={"query": query},
        timeout=10
    )

    if r2.status_code == 200:
        docs2 = r2.json().get("documents", [])
        for d in docs2:
            results.append({
                "name": d.get("address_name", ""),
                "address": d.get("address_name", ""),
                "road_address": "",
                "lat": float(d["y"]),
                "lng": float(d["x"])
            })

    # 중복 제거
    dedup = []
    seen = set()

    for r in results:
        key = (round(r["lat"], 6), round(r["lng"], 6), r["address"])
        if key not in seen:
            seen.add(key)
            dedup.append(r)

    return dedup[:20]

# -----------------------------
# 카카오 길찾기
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

    data = r.json()
    routes = data.get("routes", [])

    if not routes:
        return None, None

    summary = routes[0].get("summary")
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
st.caption("광역시도와 장소명을 기준으로 위치를 찾은 뒤, 선택한 위치 기준 생활권을 분석합니다.")

c1, c2, c3 = st.columns([2, 2, 3])

with c1:
    sido = st.selectbox("광역시도", SIDO_OPTIONS)

with c2:
    sigungu = st.text_input("시군구(선택)", placeholder="예: 파주시 / 포항시 북구")

with c3:
    place_name = st.text_input("기준 장소명", placeholder="예: 보성아파트, 이마트 죽전점")

b1, b2 = st.columns([1, 1])

with b1:
    search_btn = st.button("🔍 위치 찾기", use_container_width=True)

with b2:
    reset_btn = st.button("초기화", use_container_width=True)

if reset_btn:
    st.session_state.search_results = []
    st.session_state.selected_origin = None
    st.session_state.result_df = None
    st.session_state.searched_query = ""
    st.rerun()

# -----------------------------
# 위치 검색
# -----------------------------
if search_btn:
    if not sido or not place_name.strip():
        st.warning("광역시도와 기준 장소명은 반드시 입력해주세요.")
        st.stop()

    full_query = f"{sido} {sigungu.strip()} {place_name.strip()}".strip()
    full_query = " ".join(full_query.split())

    st.session_state.searched_query = full_query
    st.session_state.selected_origin = None
    st.session_state.result_df = None

    with st.spinner("위치를 찾는 중..."):
        results = search_kakao(full_query)

    if not results:
        st.warning("검색 결과가 없습니다. 장소명을 조금 더 구체적으로 입력해보세요.")
        st.session_state.search_results = []
    else:
        st.session_state.search_results = results

# -----------------------------
# 검색 결과 표시 및 선택
# -----------------------------
if st.session_state.search_results:
    st.subheader("검색 결과")
    st.write(f"검색어: **{st.session_state.searched_query}**")
    st.write("찾으시는 위치가 맞는지 확인해주세요.")

    option_labels = []
    for r in st.session_state.search_results:
        road = f" / 도로명: {r['road_address']}" if r["road_address"] else ""
        label = f"{r['name']} / 지번: {r['address']}{road}"
        option_labels.append(label)

    selected_label = st.radio("검색 결과 선택", option_labels, index=0)

    selected_idx = option_labels.index(selected_label)
    st.session_state.selected_origin = st.session_state.search_results[selected_idx]

# -----------------------------
# 분석 실행
# -----------------------------
if st.session_state.selected_origin:
    origin = st.session_state.selected_origin

    st.success(f"선택된 위치: {origin['address']}")

    n_min = st.number_input("차로 몇 분?", min_value=1, max_value=180, value=30)

    run_btn = st.button("🚀 분석 실행", use_container_width=True)

    if run_btn:
        progress_bar = st.progress(0)
        status_text = st.empty()

        origin_lat = origin["lat"]
        origin_lng = origin["lng"]

        # 1. 데이터 로딩
        status_text.write("📂 행정동 데이터를 불러오는 중...")
        progress_bar.progress(15)

        df = load_data()
        df = df.dropna(subset=["lat", "lng"]).copy()

        # 행정동 None/빈값 제거
        df["행정동명_전체"] = df["행정동명_전체"].astype(str).str.strip()
        df = df[
            df["행정동명_전체"].notna() &
            (df["행정동명_전체"] != "") &
            (df["행정동명_전체"].str.lower() != "none")
        ].copy()

        # 2. 직선거리 계산
        status_text.write("📏 후보 행정동 거리를 계산하는 중...")
        progress_bar.progress(30)

        df["직선거리_km"] = df.apply(
            lambda row: haversine(origin_lat, origin_lng, row["lat"], row["lng"]),
            axis=1
        )

        # 현재는 기존 방식 유지: 25km 이내 후보
        candidates = df[df["직선거리_km"] <= 25].copy()
        candidates = candidates.sort_values("직선거리_km").reset_index(drop=True)

        total_candidates = len(candidates)

        if total_candidates == 0:
            progress_bar.progress(100)
            status_text.write("⚠️ 후보 행정동이 없습니다.")
            st.warning("후보 행정동이 없습니다.")
            st.stop()

        # 3. 이동시간 계산
        status_text.write(f"🚗 이동시간 계산 중... 0/{total_candidates}")
        progress_bar.progress(45)

        results = []
        limit_sec = n_min * 60

        for idx, (_, row) in enumerate(candidates.iterrows(), start=1):
            percent = int(45 + (idx / total_candidates) * 45)
            progress_bar.progress(percent)
            status_text.write(f"🚗 이동시간 계산 중... {idx}/{total_candidates}")

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

            time.sleep(0.02)

        # 4. 결과 정리
        status_text.write("📊 결과를 정리하는 중...")
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

        progress_bar.progress(100)
        status_text.write("✅ 분석 완료")

# -----------------------------
# 결과 출력
# -----------------------------
if st.session_state.result_df is not None:
    st.subheader("분석 결과")

    st.caption(
        "※ 이동시간은 행정동 대표 좌표(중심점) 기준으로 계산되며, "
        "카카오맵에서 조회되는 특정 시설 기준 길찾기와 차이가 있을 수 있습니다."
    )

    if st.session_state.result_df.empty:
        st.warning("해당 조건에서 생활권으로 포함되는 행정동이 없습니다.")
    else:
        st.write(f"총 {len(st.session_state.result_df)}개 행정동 포함")
        st.dataframe(st.session_state.result_df, use_container_width=True)
