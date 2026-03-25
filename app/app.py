import streamlit as st
import pandas as pd
import requests
import math
import time
import urllib.parse
from pathlib import Path

st.set_page_config(page_title="생활권 인구 분석", page_icon="🚗", layout="wide")

KAKAO_REST_KEY = st.secrets["KAKAO_REST_KEY"]

# -----------------------------
# 상태 초기화
# -----------------------------
if "cancel_requested" not in st.session_state:
    st.session_state.cancel_requested = False

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
# 반경 계산 (하드코딩 제거)
# -----------------------------
def get_radius_km_by_minutes(n_min, factor=0.7, max_radius=100):
    return min(n_min * factor, max_radius)

# -----------------------------
# 주소 → 좌표
# -----------------------------
def geocode_kakao(query):
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_KEY}"}
    full_url = f"{url}?query={urllib.parse.quote(query)}"

    r = requests.get(full_url, headers=headers, timeout=10)

    if r.status_code != 200:
        return None

    docs = r.json().get("documents", [])
    if not docs:
        return None

    d0 = docs[0]
    return {"lat": float(d0["y"]), "lng": float(d0["x"]), "address_name": d0["address_name"]}

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
# 연령 그룹
# -----------------------------
population_options = {
    "총인구": ["총인구수"],
    "영유아(0~9세)": ["0_4세","5_9세"],
    "초중고(10~18세)": ["10_12세","13_15세","16_18세"],
    "청년층(19~34세)": ["19_24세","25_34세"],
    "중장년층(35~64세)": ["35_49세","50_64세"],
    "고령층(65+)": ["65세이상"]
}

# -----------------------------
# UI
# -----------------------------
st.title("🚗 생활권 인구 분석")

col1, col2 = st.columns([4,1])

with col1:
    address = st.text_input("기준 주소", "와동동 1412")
    n_min = st.number_input("차로 몇 분?", 1, 180, 30)
    selected_group = st.selectbox("분석 대상", list(population_options.keys()))

with col2:
    st.write("")
    run = st.button("분석 실행", use_container_width=True)
    cancel = st.button("⛔ 분석 취소", use_container_width=True)

if cancel:
    st.session_state.cancel_requested = True

# -----------------------------
# 실행
# -----------------------------
if run:

    st.session_state.cancel_requested = False

    progress_bar = st.progress(0)
    status = st.empty()

    status.write("📍 주소 변환 중...")
    progress_bar.progress(10)

    origin = geocode_kakao(address)

    if origin is None:
        st.error("주소를 찾을 수 없습니다.")
        st.stop()

    origin_lat = origin["lat"]
    origin_lng = origin["lng"]

    status.write("📂 데이터 로딩 중...")
    progress_bar.progress(20)

    df = load_data()
    df = df.dropna(subset=["lat","lng"]).copy()

    selected_cols = population_options[selected_group]
    df["선택인구"] = df[selected_cols].fillna(0).sum(axis=1)

    status.write("📏 후보 추출 중...")
    progress_bar.progress(35)

    df["직선거리_km"] = df.apply(
        lambda r: haversine(origin_lat, origin_lng, r["lat"], r["lng"]), axis=1
    )

    radius = get_radius_km_by_minutes(n_min)

    candidates = df[
        (df["직선거리_km"] <= radius) &
        (df["선택인구"] > 0)
    ].sort_values("직선거리_km").head(120)

    status.write(f"🚗 이동시간 계산 중... (총 {len(candidates)}개)")
    progress_bar.progress(50)

    results = []
    limit_sec = n_min * 60

    for i, (_, row) in enumerate(candidates.iterrows()):

        # 🔥 취소 체크
        if st.session_state.cancel_requested:
            status.write("⛔ 분석이 중단되었습니다.")
            progress_bar.empty()
            st.stop()

        percent = int(50 + (i/len(candidates))*40)
        progress_bar.progress(percent)
        status.write(f"🚗 계산 중 {i+1}/{len(candidates)}")

        dur, dist = drive_seconds_kakao(
            origin_lng, origin_lat, row["lng"], row["lat"]
        )

        if dur and dur <= limit_sec:
            results.append({
                "행정동": row["행정동명_전체"],
                "이동시간(분)": round(dur/60,1),
                "거리(km)": round(dist/1000,1),
                "인구수": int(row["선택인구"])
            })

        time.sleep(0.03)

    progress_bar.progress(100)
    status.write("✅ 완료")

    result_df = pd.DataFrame(results)

    if result_df.empty:
        st.warning("결과 없음")
        st.stop()

    total = int(result_df["인구수"].sum())

    c1, c2 = st.columns(2)
    c1.metric("행정동 수", len(result_df))
    c2.metric(f"{selected_group}", f"{total:,}명")

    st.dataframe(result_df.sort_values("이동시간(분)"), use_container_width=True)
