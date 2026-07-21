import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st


# ---------------------------------------------------------
# 페이지 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="서울시 영유아·어린이집 공급 현황",
    page_icon="🏫",
    layout="wide",
)

POPULATION_FILE = "202606_202606_서울시.csv"
CHILDCARE_FILE = "서울시 어린이집 정보(표준 데이터).csv"

AGE_COLUMNS = {
    age: f"2026년06월_계_{age}세"
    for age in range(6)
}


# ---------------------------------------------------------
# 화면 스타일
# ---------------------------------------------------------
st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; padding-bottom: 3rem;}
    .main-title {font-size: 2rem; font-weight: 750; margin-bottom: 0.15rem;}
    .sub-title {color: #5f6368; margin-bottom: 1.5rem;}
    div[data-testid="stMetric"] {
        border: 1px solid #e3e7ee;
        border-radius: 12px;
        padding: 16px;
        background: white;
    }
    .status-box {
        border-radius: 12px;
        padding: 18px 20px;
        margin: 12px 0 20px 0;
        font-size: 1.15rem;
        font-weight: 700;
    }
    .status-ok {background: #eaf7ee; border: 1px solid #9bd4aa; color: #176b34;}
    .status-low {background: #fff0f0; border: 1px solid #e8a4a4; color: #a11f1f;}
    .status-none {background: #fff7e6; border: 1px solid #e3c26f; color: #805d00;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# 파일 읽기
# ---------------------------------------------------------
def find_file(filename: str) -> Path:
    """로컬 실행과 Streamlit Cloud 실행을 모두 지원합니다."""
    candidates = [
        Path(filename),
        Path(__file__).resolve().parent / filename,
        Path("/mnt/data") / filename,
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"'{filename}' 파일을 찾을 수 없습니다. app.py와 같은 폴더에 올려 주세요."
    )


def read_csv_with_korean_encoding(path: Path) -> pd.DataFrame:
    for encoding in ("cp949", "utf-8-sig", "euc-kr", "utf-8"):
        try:
            return pd.read_csv(path, encoding=encoding, dtype=str)
        except UnicodeDecodeError:
            continue

    raise ValueError(f"{path.name}의 문자 인코딩을 확인해 주세요.")


# ---------------------------------------------------------
# 행정구역 정리
# ---------------------------------------------------------
def remove_area_code(text: str) -> str:
    """행정구역명 뒤의 10자리 코드를 제거합니다."""
    if pd.isna(text):
        return ""

    return re.sub(r"\s*\(\d{10}\)\s*$", "", str(text)).strip()


def normalize_dong_group(name: str) -> str:
    """
    주소의 법정동과 인구자료의 행정동을 비교하기 위한 동 그룹명입니다.

    예:
    신정1동, 신정2동, 신정7동 -> 신정동
    창신제1동 -> 창신동
    잠실본동 -> 잠실동
    상계10동 -> 상계동
    """
    if pd.isna(name):
        return ""

    text = str(name).strip()
    text = re.sub(r"\s+", "", text)

    # '제1동', '1동', '본동'을 법정동 성격의 기본 이름으로 통합
    text = re.sub(r"제\d+동$", "동", text)
    text = re.sub(r"\d+동$", "동", text)
    text = re.sub(r"본동$", "동", text)

    return text


def extract_dong_from_address(address: str) -> str:
    """상세주소에서 법정동 또는 가 명칭을 추출합니다."""
    if pd.isna(address):
        return ""

    text = str(address).strip()

    # 괄호 안 첫 부분이 가장 안정적으로 법정동을 포함하는 경우가 많음
    bracket_parts = re.findall(r"\(([^)]*)\)", text)
    search_parts = bracket_parts + [text]

    # 동/가 후보를 찾되 아파트 동(예: 101동)은 제외
    pattern = r"(?<!\d)([가-힣]+(?:\d+가|가|동))"

    for part in search_parts:
        candidates = re.findall(pattern, part)
        if candidates:
            # '서울특별시', '공동' 등 잘못 잡힐 수 있는 후보 제거
            valid = [
                c for c in candidates
                if c not in {"공동", "이동", "자동"}
                and not re.fullmatch(r"\d+동", c)
            ]
            if valid:
                return valid[0]

    return ""


# 일부 복합 행정동은 여러 법정동을 묶고 있어 주소 기반 동과 직접 연결하기 어렵습니다.
# 아래 별칭은 대표적인 복합 행정동을 주소 기반 동 그룹으로 풀어 합산하기 위한 것입니다.
COMPOSITE_DONG_ALIASES = {
    "청운효자동": ["청운동", "효자동", "신교동", "궁정동", "누상동", "누하동", "옥인동", "통인동", "창성동"],
    "종로1.2.3.4가동": ["종로1가", "종로2가", "종로3가", "종로4가"],
    "종로5.6가동": ["종로5가", "종로6가"],
}


@st.cache_data(show_spinner=False)
def load_and_prepare_data():
    population_path = find_file(POPULATION_FILE)
    childcare_path = find_file(CHILDCARE_FILE)

    pop = read_csv_with_korean_encoding(population_path)
    child = read_csv_with_korean_encoding(childcare_path)

    # 필수 열 확인
    required_pop = {"행정구역", *AGE_COLUMNS.values()}
    required_child = {
        "시군구명", "어린이집명", "운영현황", "상세주소",
        "시설 위도(좌표값)", "시설 경도(좌표값)", "데이터기준일자"
    }

    missing_pop = required_pop - set(pop.columns)
    missing_child = required_child - set(child.columns)

    if missing_pop:
        raise ValueError(f"인구자료에 필요한 열이 없습니다: {sorted(missing_pop)}")
    if missing_child:
        raise ValueError(f"어린이집 자료에 필요한 열이 없습니다: {sorted(missing_child)}")

    # ---------------- 인구자료 ----------------
    pop["행정구역_정리"] = pop["행정구역"].apply(remove_area_code)
    pop = pop[pop["행정구역_정리"].str.startswith("서울특별시 ", na=False)].copy()

    # 서울시 전체행과 자치구 합계행을 제외하고 행정동 행만 사용
    parts = pop["행정구역_정리"].str.split()
    pop["자치구"] = parts.str[1]
    pop["행정동"] = parts.apply(lambda x: " ".join(x[2:]) if len(x) >= 3 else "")
    pop = pop[pop["행정동"] != ""].copy()

    for age, col in AGE_COLUMNS.items():
        pop[col] = pd.to_numeric(
            pop[col].str.replace(",", "", regex=False),
            errors="coerce",
        ).fillna(0).astype(int)

    pop["동그룹"] = pop["행정동"].apply(normalize_dong_group)

    # 복합 행정동은 대표 동그룹 하나로 두지 않고 별칭별로 분배할 수 없으므로
    # 하나의 복합 동그룹으로 유지합니다. 어린이집 주소와 직접 매칭되지 않을 수 있습니다.

    pop_grouped = (
        pop.groupby(["자치구", "동그룹"], as_index=False)[list(AGE_COLUMNS.values())]
        .sum()
    )
    pop_grouped["0~5세 아동수"] = pop_grouped[list(AGE_COLUMNS.values())].sum(axis=1)

    # ---------------- 어린이집자료 ----------------
    child = child[child["운영현황"].eq("정상")].copy()
    child["동_주소추출"] = child["상세주소"].apply(extract_dong_from_address)
    child["동그룹"] = child["동_주소추출"].apply(normalize_dong_group)

    child["위도"] = pd.to_numeric(child["시설 위도(좌표값)"], errors="coerce")
    child["경도"] = pd.to_numeric(child["시설 경도(좌표값)"], errors="coerce")

    child_valid = child[
        child["시군구명"].notna()
        & child["동그룹"].ne("")
    ].copy()

    child_grouped = (
        child_valid.groupby(["시군구명", "동그룹"], as_index=False)
        .agg(
            어린이집수=("어린이집코드", "nunique"),
            어린이집행수=("어린이집명", "size"),
        )
        .rename(columns={"시군구명": "자치구"})
    )

    # 인구와 어린이집 결합
    summary = pop_grouped.merge(
        child_grouped[["자치구", "동그룹", "어린이집수"]],
        on=["자치구", "동그룹"],
        how="left",
    )
    summary["어린이집수"] = summary["어린이집수"].fillna(0).astype(int)
    summary["어린이집 1개소당 아동수"] = summary.apply(
        lambda row: (
            row["0~5세 아동수"] / row["어린이집수"]
            if row["어린이집수"] > 0 else float("inf")
        ),
        axis=1,
    )

    # 서울 전체 공급 평균: 정상 운영 어린이집 / 0~5세 전체 아동
    seoul_children = int(summary["0~5세 아동수"].sum())
    seoul_centers = int(child["어린이집코드"].nunique())
    seoul_children_per_center = (
        seoul_children / seoul_centers if seoul_centers else float("inf")
    )

    data_date = (
        child["데이터기준일자"].dropna().astype(str).mode().iloc[0]
        if not child["데이터기준일자"].dropna().empty
        else "확인 불가"
    )

    return summary, child_valid, seoul_children, seoul_centers, seoul_children_per_center, data_date


# ---------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------
st.markdown('<div class="main-title">서울시 영유아·어린이집 공급 현황</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">자치구와 동을 선택하면 0~5세 인구와 어린이집 공급 수준을 확인할 수 있습니다.</div>',
    unsafe_allow_html=True,
)

try:
    (
        summary,
        childcare,
        seoul_children,
        seoul_centers,
        seoul_children_per_center,
        childcare_data_date,
    ) = load_and_prepare_data()
except Exception as error:
    st.error(str(error))
    st.info(
        f"GitHub 저장소에서 app.py와 함께 '{POPULATION_FILE}', "
        f"'{CHILDCARE_FILE}' 파일을 같은 폴더에 두어야 합니다."
    )
    st.stop()


# ---------------------------------------------------------
# 사이드바 선택
# ---------------------------------------------------------
with st.sidebar:
    st.header("지역 선택")

    gu_list = sorted(summary["자치구"].dropna().unique())
    selected_gu = st.selectbox("자치구", gu_list)

    dong_list = sorted(
        summary.loc[summary["자치구"].eq(selected_gu), "동그룹"]
        .dropna()
        .unique()
    )
    selected_dong = st.selectbox("동", dong_list)

    st.divider()
    st.caption("인구 기준: 2026년 6월")
    st.caption(f"어린이집 기준: {childcare_data_date}")
    st.caption("정상 운영 어린이집만 집계")


# ---------------------------------------------------------
# 선택 지역 결과
# ---------------------------------------------------------
selected = summary[
    summary["자치구"].eq(selected_gu)
    & summary["동그룹"].eq(selected_dong)
].iloc[0]

age_values = {
    age: int(selected[col])
    for age, col in AGE_COLUMNS.items()
}

total_children = int(selected["0~5세 아동수"])
center_count = int(selected["어린이집수"])
local_children_per_center = selected["어린이집 1개소당 아동수"]

selected_childcare = childcare[
    childcare["시군구명"].eq(selected_gu)
    & childcare["동그룹"].eq(selected_dong)
].copy()

st.markdown(f"## {selected_gu} {selected_dong}")

# 연령별 지표 6개
age_cols = st.columns(6)
for age, col in zip(range(6), age_cols):
    col.metric(f"{age}세", f"{age_values[age]:,}명")

st.write("")

metric1, metric2, metric3, metric4 = st.columns(4)
metric1.metric("0~5세 아동 수", f"{total_children:,}명")
metric2.metric("정상 운영 어린이집", f"{center_count:,}개소")
metric3.metric(
    "어린이집 1개소당 아동",
    "해당 없음" if center_count == 0 else f"{local_children_per_center:,.1f}명",
)
metric4.metric("서울시 전체 평균", f"{seoul_children_per_center:,.1f}명")

# 공급 판단
if center_count == 0:
    status_text = "부족합니다"
    status_detail = "정상 운영 중인 어린이집이 확인되지 않습니다."
    status_class = "status-none"
elif local_children_per_center > seoul_children_per_center:
    status_text = "부족합니다"
    status_detail = (
        f"어린이집 1개소당 아동 수가 서울시 평균보다 "
        f"{local_children_per_center - seoul_children_per_center:,.1f}명 많습니다."
    )
    status_class = "status-low"
else:
    status_text = "충분합니다"
    status_detail = (
        f"어린이집 1개소당 아동 수가 서울시 평균보다 "
        f"{seoul_children_per_center - local_children_per_center:,.1f}명 적거나 같습니다."
    )
    status_class = "status-ok"

st.markdown(
    f'<div class="status-box {status_class}">어린이집 공급이 {status_text}.<br>'
    f'<span style="font-size:0.95rem;font-weight:500;">{status_detail}</span></div>',
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# 그래프와 지도
# ---------------------------------------------------------
left, right = st.columns([1, 1])

with left:
    st.subheader("연령별 아동 수")
    age_chart = pd.DataFrame(
        {
            "연령": [f"{age}세" for age in range(6)],
            "아동 수": [age_values[age] for age in range(6)],
        }
    ).set_index("연령")
    st.bar_chart(age_chart, y="아동 수")

with right:
    st.subheader("어린이집 위치")
    map_data = selected_childcare[["위도", "경도"]].dropna().rename(
        columns={"위도": "lat", "경도": "lon"}
    )

    # 서울 범위를 크게 벗어나는 잘못된 좌표 제외
    map_data = map_data[
        map_data["lat"].between(37.3, 37.8)
        & map_data["lon"].between(126.7, 127.3)
    ]

    if map_data.empty:
        st.info("표시할 수 있는 위도·경도 정보가 없습니다.")
    else:
        st.map(map_data, latitude="lat", longitude="lon", size=35)


# ---------------------------------------------------------
# 어린이집 목록
# ---------------------------------------------------------
st.subheader("어린이집 목록")

if selected_childcare.empty:
    st.warning("주소에서 해당 동으로 확인된 정상 운영 어린이집이 없습니다.")
else:
    list_columns = [
        "어린이집명",
        "어린이집유형",
        "상세주소",
        "전화번호",
        "정원",
        "현원",
        "제공서비스",
    ]
    list_columns = [col for col in list_columns if col in selected_childcare.columns]

    display_df = selected_childcare[list_columns].sort_values("어린이집명").reset_index(drop=True)
    st.dataframe(display_df, hide_index=True, use_container_width=True)

    csv_bytes = display_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "선택 지역 어린이집 목록 내려받기",
        data=csv_bytes,
        file_name=f"{selected_gu}_{selected_dong}_어린이집목록.csv",
        mime="text/csv",
    )


# ---------------------------------------------------------
# 설명 및 주의사항
# ---------------------------------------------------------
with st.expander("공급 판단 기준과 자료 해석 시 주의사항"):
    st.markdown(
        f"""
        **공급 판단식**

        - 선택 지역 값 = 선택 지역 0~5세 아동 수 ÷ 정상 운영 어린이집 수
        - 서울시 평균 = 서울시 전체 0~5세 아동 수 ÷ 서울시 정상 운영 어린이집 수
        - 선택 지역의 어린이집 1개소당 아동 수가 서울시 평균({seoul_children_per_center:,.1f}명)보다 많으면 **부족합니다**로 표시합니다.
        - 평균보다 적거나 같으면 **충분합니다**로 표시합니다.

        **동 단위에 관한 주의**

        어린이집 자료는 주소의 법정동을 사용하고, 인구자료는 행정동을 사용합니다.  
        이를 비교하기 위해 `신정1동~신정7동 → 신정동`, `잠실본동·잠실2동 등 → 잠실동`처럼 번호가 붙은 행정동을 하나의 동 그룹으로 합산했습니다.
        따라서 이 결과는 개별 행정동보다 **주소 기반 동 그룹의 상대적 공급 수준**으로 해석하는 것이 적절합니다.

        **기준시점**

        - 인구: 2026년 6월
        - 어린이집: {childcare_data_date}
        - 어린이집은 운영현황이 `정상`인 시설만 포함
        """
    )

st.caption(
    f"서울시 전체: 0~5세 아동 {seoul_children:,}명, 정상 운영 어린이집 {seoul_centers:,}개소"
)
