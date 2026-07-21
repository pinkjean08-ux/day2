import io
import re

import pandas as pd
import streamlit as st


# ---------------------------------------------------------
# 페이지 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="전남광주특별시 영유아·어린이집 현황",
    page_icon="🏫",
    layout="wide",
)


# ---------------------------------------------------------
# 기본 스타일
# ---------------------------------------------------------
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }

    .sub-title {
        color: #666666;
        margin-bottom: 1.5rem;
    }

    div[data-testid="stMetric"] {
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 16px;
        background-color: white;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# 보조 함수
# ---------------------------------------------------------
def clean_column_names(df):
    """열 이름의 줄바꿈, 앞뒤 공백 등을 정리합니다."""
    cleaned = df.copy()

    cleaned.columns = [
        re.sub(r"\s+", " ", str(col).replace("\n", " ")).strip()
        for col in cleaned.columns
    ]

    return cleaned


def read_uploaded_file(uploaded_file):
    """CSV 또는 Excel 파일을 읽습니다."""
    if uploaded_file is None:
        return None

    file_name = uploaded_file.name.lower()
    file_bytes = uploaded_file.getvalue()

    if file_name.endswith(".csv"):
        encodings = ["utf-8-sig", "cp949", "euc-kr", "utf-8"]

        for encoding in encodings:
            try:
                return pd.read_csv(
                    io.BytesIO(file_bytes),
                    encoding=encoding,
                    dtype=str,
                )
            except UnicodeDecodeError:
                continue
            except Exception:
                continue

        raise ValueError(
            "CSV 파일을 읽을 수 없습니다. UTF-8 또는 CP949 형식으로 저장해 주세요."
        )

    if file_name.endswith((".xlsx", ".xls")):
        return pd.read_excel(
            io.BytesIO(file_bytes),
            dtype=str,
        )

    raise ValueError("CSV, XLSX 또는 XLS 파일만 업로드할 수 있습니다.")


def normalize_area_name(value):
    """
    행정구역명을 비교하기 쉽게 정리합니다.

    예:
    '광주광역시 북구 용봉동' → '용봉동'
    ' 용봉동(행정동) ' → '용봉동'
    """
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.lower() in ["nan", "none", "null"]:
        return ""

    # 괄호와 괄호 안 내용 제거
    text = re.sub(r"\([^)]*\)", "", text)

    # 전각 공백, 일반 공백 제거
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text).strip()

    # 전체 주소처럼 입력된 경우 마지막 행정구역 단위 사용
    tokens = text.split()

    area_tokens = [
        token
        for token in tokens
        if re.search(r"(읍|면|동|가)$", token)
    ]

    if area_tokens:
        text = area_tokens[-1]

    # 숫자 뒤에 붙은 불필요한 점 정리
    text = text.replace(".", "")

    # 모든 공백 제거
    text = re.sub(r"\s+", "", text)

    return text


def normalize_region_name(value):
    """시도 및 시군구 명칭을 비교하기 쉽게 정리합니다."""
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.lower() in ["nan", "none", "null"]:
        return ""

    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\s+", "", text)

    return text


def convert_numeric(series):
    """쉼표, 명, 개 등의 문자가 포함된 값을 숫자로 변환합니다."""
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("명", "", regex=False)
        .str.replace("개", "", regex=False)
        .str.replace("-", "", regex=False)
        .str.strip()
    )

    return pd.to_numeric(cleaned, errors="coerce").fillna(0)


def guess_column(columns, keywords):
    """열 이름에 키워드가 포함된 첫 번째 열을 찾습니다."""
    columns = list(columns)

    for keyword in keywords:
        for column in columns:
            if keyword.lower() in str(column).lower():
                return column

    return None


def column_index(columns, guessed_column):
    """selectbox 기본 위치를 계산합니다."""
    columns = list(columns)

    if guessed_column in columns:
        return columns.index(guessed_column)

    return 0


def age_from_column_name(column_name):
    """
    열 이름에서 0~5세 연령을 추출합니다.

    인식 예:
    0세, 만0세, 0 세, age_0
    """
    text = str(column_name).lower()
    text = text.replace("만", "")
    text = re.sub(r"\s+", "", text)

    patterns = [
        r"^([0-5])세$",
        r"^([0-5])세인구$",
        r"^([0-5])세아동$",
        r"^age[_-]?([0-5])$",
        r"^([0-5])$",
    ]

    for pattern in patterns:
        matched = re.match(pattern, text)

        if matched:
            return int(matched.group(1))

    return None


def detect_age_columns(columns):
    """0~5세에 해당하는 열을 자동 탐지합니다."""
    result = {}

    for column in columns:
        age = age_from_column_name(column)

        if age is not None and age not in result:
            result[age] = column

    return result


def count_children_long_format(
    df,
    area_column,
    age_column,
    population_column,
):
    """
    연령이 행으로 구성된 자료를 처리합니다.

    예:
    읍면동 | 연령 | 인구수
    용봉동 | 0세 | 520
    용봉동 | 1세 | 498
    """
    work = df.copy()

    work["_area_key"] = work[area_column].apply(normalize_area_name)

    age_text = (
        work[age_column]
        .astype(str)
        .str.replace("만", "", regex=False)
        .str.extract(r"(\d+)", expand=False)
    )

    work["_age"] = pd.to_numeric(age_text, errors="coerce")
    work["_population"] = convert_numeric(work[population_column])

    work = work[work["_age"].between(0, 5, inclusive="both")]

    result = (
        work.groupby(["_area_key", "_age"], as_index=False)["_population"]
        .sum()
        .rename(
            columns={
                "_area_key": "행정구역키",
                "_age": "연령",
                "_population": "아동수",
            }
        )
    )

    result["연령"] = result["연령"].astype(int)

    return result


def count_children_wide_format(
    df,
    area_column,
    selected_age_columns,
):
    """
    연령이 열로 구성된 자료를 처리합니다.

    예:
    읍면동 | 0세 | 1세 | 2세 | ... | 5세
    """
    work = df.copy()
    work["_area_key"] = work[area_column].apply(normalize_area_name)

    records = []

    for age, column in selected_age_columns.items():
        temp = pd.DataFrame(
            {
                "행정구역키": work["_area_key"],
                "연령": age,
                "아동수": convert_numeric(work[column]),
            }
        )

        records.append(temp)

    result = pd.concat(records, ignore_index=True)

    result = (
        result.groupby(["행정구역키", "연령"], as_index=False)["아동수"]
        .sum()
    )

    return result


# ---------------------------------------------------------
# 제목
# ---------------------------------------------------------
st.markdown(
    '<div class="main-title">전남광주특별시 영유아·어린이집 현황</div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="sub-title">'
    "읍면동을 선택하면 0~5세 아동 수와 어린이집 현황을 확인할 수 있습니다."
    "</div>",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# 사이드바: 파일 업로드
# ---------------------------------------------------------
with st.sidebar:
    st.header("1. 자료 업로드")

    population_file = st.file_uploader(
        "연령별 인구 자료",
        type=["csv", "xlsx", "xls"],
        help="읍면동별 0~5세 인구가 포함된 자료를 업로드하세요.",
    )

    childcare_file = st.file_uploader(
        "어린이집 현황 자료",
        type=["csv", "xlsx", "xls"],
        help="어린이집명과 읍면동 또는 주소가 포함된 자료를 업로드하세요.",
    )

    st.divider()

    st.caption(
        "자료는 외부 서버에 별도로 저장하지 않고 현재 앱 실행 중에만 사용됩니다."
    )


# ---------------------------------------------------------
# 파일 확인
# ---------------------------------------------------------
if population_file is None or childcare_file is None:
    st.info("왼쪽 메뉴에서 연령별 인구 자료와 어린이집 현황 자료를 업로드해 주세요.")

    st.markdown(
        """
        ### 권장 자료 구조

        **연령별 인구 자료**

        다음 두 형식 중 하나를 사용할 수 있습니다.

        | 읍면동 | 0세 | 1세 | 2세 | 3세 | 4세 | 5세 |
        |---|---:|---:|---:|---:|---:|---:|
        | 용봉동 | 520 | 498 | 510 | 503 | 519 | 530 |

        또는

        | 읍면동 | 연령 | 인구수 |
        |---|---|---:|
        | 용봉동 | 0세 | 520 |
        | 용봉동 | 1세 | 498 |

        **어린이집 현황 자료**

        | 어린이집명 | 시군구 | 읍면동 | 주소 |
        |---|---|---|---|
        | 행복어린이집 | 북구 | 용봉동 | 광주광역시 북구 용봉동 ... |
        """
    )

    st.stop()


# ---------------------------------------------------------
# 자료 읽기
# ---------------------------------------------------------
try:
    population_raw = clean_column_names(read_uploaded_file(population_file))
    childcare_raw = clean_column_names(read_uploaded_file(childcare_file))

except Exception as error:
    st.error(f"파일을 읽는 중 오류가 발생했습니다: {error}")
    st.stop()


if population_raw.empty:
    st.error("연령별 인구 자료에 데이터가 없습니다.")
    st.stop()

if childcare_raw.empty:
    st.error("어린이집 현황 자료에 데이터가 없습니다.")
    st.stop()


# ---------------------------------------------------------
# 사이드바: 열 설정
# ---------------------------------------------------------
with st.sidebar:
    st.header("2. 열 설정")

    population_columns = list(population_raw.columns)
    childcare_columns = list(childcare_raw.columns)

    guessed_population_area = guess_column(
        population_columns,
        [
            "읍면동명",
            "행정동명",
            "행정동",
            "읍면동",
            "법정동",
            "지역명",
        ],
    )

    population_area_column = st.selectbox(
        "인구 자료의 읍면동 열",
        population_columns,
        index=column_index(
            population_columns,
            guessed_population_area,
        ),
    )

    guessed_childcare_area = guess_column(
        childcare_columns,
        [
            "읍면동명",
            "행정동명",
            "행정동",
            "읍면동",
            "법정동",
            "동명",
            "주소",
        ],
    )

    childcare_area_column = st.selectbox(
        "어린이집 자료의 읍면동 또는 주소 열",
        childcare_columns,
        index=column_index(
            childcare_columns,
            guessed_childcare_area,
        ),
    )

    guessed_name_column = guess_column(
        childcare_columns,
        [
            "어린이집명",
            "시설명",
            "기관명",
            "명칭",
        ],
    )

    childcare_name_column = st.selectbox(
        "어린이집 이름 열",
        childcare_columns,
        index=column_index(
            childcare_columns,
            guessed_name_column,
        ),
    )

    st.divider()

    st.subheader("인구 자료 구조")

    detected_age_columns = detect_age_columns(population_columns)

    if len(detected_age_columns) >= 3:
        default_format_index = 0
    else:
        default_format_index = 1

    population_format = st.radio(
        "0~5세 인구의 배치 방식",
        [
            "연령이 각각 다른 열에 있음",
            "연령이 행에 있음",
        ],
        index=default_format_index,
    )


# ---------------------------------------------------------
# 인구 자료 변환
# ---------------------------------------------------------
if population_format == "연령이 각각 다른 열에 있음":
    selected_age_columns = {}

    with st.sidebar:
        st.caption("각 연령에 해당하는 열을 선택하세요.")

        for age in range(6):
            default_column = detected_age_columns.get(age)
            default_index = column_index(
                population_columns,
                default_column,
            )

            selected_column = st.selectbox(
                f"{age}세 인구 열",
                population_columns,
                index=default_index,
                key=f"age_column_{age}",
            )

            selected_age_columns[age] = selected_column

    # 같은 열이 여러 연령에 중복 지정되었는지 확인
    if len(set(selected_age_columns.values())) < 6:
        st.warning(
            "일부 연령에 동일한 열이 선택되어 있습니다. "
            "왼쪽 열 설정에서 0~5세 열을 각각 확인해 주세요."
        )

    population_long = count_children_wide_format(
        population_raw,
        population_area_column,
        selected_age_columns,
    )

else:
    guessed_age_column = guess_column(
        population_columns,
        ["만나이", "연령", "나이", "세"],
    )

    guessed_population_column = guess_column(
        population_columns,
        [
            "총인구수",
            "인구수",
            "아동수",
            "내국인",
            "계",
        ],
    )

    with st.sidebar:
        age_column = st.selectbox(
            "연령 열",
            population_columns,
            index=column_index(
                population_columns,
                guessed_age_column,
            ),
        )

        population_value_column = st.selectbox(
            "인구수 열",
            population_columns,
            index=column_index(
                population_columns,
                guessed_population_column,
            ),
        )

    population_long = count_children_long_format(
        population_raw,
        population_area_column,
        age_column,
        population_value_column,
    )


# ---------------------------------------------------------
# 어린이집 자료 정리
# ---------------------------------------------------------
childcare = childcare_raw.copy()

childcare["_area_key"] = childcare[childcare_area_column].apply(
    normalize_area_name
)

childcare["_name"] = childcare[childcare_name_column].fillna("").astype(str).str.strip()

childcare = childcare[
    (childcare["_area_key"] != "")
    & (childcare["_name"] != "")
    & (childcare["_name"].str.lower() != "nan")
].copy()


# ---------------------------------------------------------
# 지역 목록 결합
# ---------------------------------------------------------
population_areas = set(
    population_long.loc[
        population_long["행정구역키"] != "",
        "행정구역키",
    ].unique()
)

childcare_areas = set(
    childcare.loc[
        childcare["_area_key"] != "",
        "_area_key",
    ].unique()
)

common_areas = sorted(population_areas.intersection(childcare_areas))
all_areas = sorted(population_areas.union(childcare_areas))


# ---------------------------------------------------------
# 자료 결합 상태 안내
# ---------------------------------------------------------
with st.expander("자료 결합 상태 확인", expanded=False):
    check_col1, check_col2, check_col3 = st.columns(3)

    check_col1.metric(
        "인구 자료 읍면동 수",
        f"{len(population_areas):,}개",
    )

    check_col2.metric(
        "어린이집 자료 읍면동 수",
        f"{len(childcare_areas):,}개",
    )

    check_col3.metric(
        "양쪽 자료 공통 읍면동",
        f"{len(common_areas):,}개",
    )

    only_population = sorted(population_areas - childcare_areas)
    only_childcare = sorted(childcare_areas - population_areas)

    mismatch_col1, mismatch_col2 = st.columns(2)

    with mismatch_col1:
        st.write("**인구 자료에만 있는 지역**")

        if only_population:
            st.write(", ".join(only_population))
        else:
            st.write("없음")

    with mismatch_col2:
        st.write("**어린이집 자료에만 있는 지역**")

        if only_childcare:
            st.write(", ".join(only_childcare))
        else:
            st.write("없음")


if not all_areas:
    st.error(
        "읍면동 정보를 찾을 수 없습니다. "
        "왼쪽 메뉴에서 읍면동 열 또는 주소 열을 다시 선택해 주세요."
    )
    st.stop()


# ---------------------------------------------------------
# 지역 선택
# ---------------------------------------------------------
st.subheader("지역 선택")

show_only_common = st.checkbox(
    "인구 자료와 어린이집 자료에 모두 있는 지역만 표시",
    value=True,
)

if show_only_common and common_areas:
    selectable_areas = common_areas
else:
    selectable_areas = all_areas

selected_area = st.selectbox(
    "읍면동",
    selectable_areas,
    index=0,
)


# ---------------------------------------------------------
# 선택 지역 데이터 집계
# ---------------------------------------------------------
selected_population = population_long[
    population_long["행정구역키"] == selected_area
].copy()

age_summary = (
    selected_population.groupby("연령", as_index=False)["아동수"]
    .sum()
    .set_index("연령")
    .reindex(range(6), fill_value=0)
    .reset_index()
)

age_summary["연령표시"] = age_summary["연령"].astype(str) + "세"
age_summary["아동수"] = age_summary["아동수"].round().astype(int)

total_children = int(age_summary["아동수"].sum())

selected_childcare = childcare[
    childcare["_area_key"] == selected_area
].copy()

# 어린이집명이 중복되어 있으면 한 시설로 계산
selected_childcare_unique = selected_childcare.drop_duplicates(
    subset=["_name"]
).copy()

childcare_count = len(selected_childcare_unique)

if childcare_count > 0:
    children_per_center = total_children / childcare_count
else:
    children_per_center = None


# ---------------------------------------------------------
# 핵심 지표
# ---------------------------------------------------------
st.markdown(f"## {selected_area} 현황")

metric_col1, metric_col2, metric_col3 = st.columns(3)

metric_col1.metric(
    "0~5세 아동 수",
    f"{total_children:,}명",
)

metric_col2.metric(
    "어린이집 수",
    f"{childcare_count:,}개",
)

metric_col3.metric(
    "어린이집 1개소당 0~5세 아동",
    (
        f"{children_per_center:,.1f}명"
        if children_per_center is not None
        else "계산 불가"
    ),
)


# ---------------------------------------------------------
# 연령별 현황
# ---------------------------------------------------------
st.subheader("연령별 아동 수")

chart_data = age_summary.set_index("연령표시")[["아동수"]]

st.bar_chart(
    chart_data,
    x_label="연령",
    y_label="아동 수",
)

display_age_summary = age_summary[["연령표시", "아동수"]].rename(
    columns={"연령표시": "연령"}
)

st.dataframe(
    display_age_summary,
    hide_index=True,
    use_container_width=True,
    column_config={
        "연령": st.column_config.TextColumn("연령"),
        "아동수": st.column_config.NumberColumn(
            "아동 수",
            format="%d명",
        ),
    },
)


# ---------------------------------------------------------
# 어린이집 목록
# ---------------------------------------------------------
st.subheader("어린이집 목록")

if selected_childcare_unique.empty:
    st.warning("선택한 읍면동의 어린이집이 자료에서 확인되지 않습니다.")

else:
    # 내부 처리용 열을 제외하고 원자료 열을 보여줌
    output_columns = [
        column
        for column in childcare_raw.columns
        if column in selected_childcare_unique.columns
    ]

    # 어린이집 이름 열을 가장 앞으로 이동
    if childcare_name_column in output_columns:
        output_columns.remove(childcare_name_column)
        output_columns.insert(0, childcare_name_column)

    childcare_display = selected_childcare_unique[
        output_columns
    ].reset_index(drop=True)

    st.dataframe(
        childcare_display,
        hide_index=True,
        use_container_width=True,
    )

    csv_data = childcare_display.to_csv(
        index=False,
        encoding="utf-8-sig",
    ).encode("utf-8-sig")

    st.download_button(
        label=f"{selected_area} 어린이집 목록 내려받기",
        data=csv_data,
        file_name=f"{selected_area}_어린이집_목록.csv",
        mime="text/csv",
    )


# ---------------------------------------------------------
# 원자료 미리보기
# ---------------------------------------------------------
with st.expander("업로드 자료 미리보기", expanded=False):
    preview_tab1, preview_tab2 = st.tabs(
        [
            "연령별 인구 자료",
            "어린이집 현황 자료",
        ]
    )

    with preview_tab1:
        st.dataframe(
            population_raw.head(100),
            hide_index=True,
            use_container_width=True,
        )

    with preview_tab2:
        st.dataframe(
            childcare_raw.head(100),
            hide_index=True,
            use_container_width=True,
        )


# ---------------------------------------------------------
# 주석
# ---------------------------------------------------------
st.divider()

st.caption(
    "주: 0~5세 아동 수는 업로드한 연령별 인구 자료를 합산한 값입니다. "
    "어린이집 수는 동일한 어린이집명이 중복된 경우 한 곳으로 계산했습니다."
)
