"""서버 지표를 그리는 Trade-off 차트. 통계·추천은 다시 계산하지 않는다."""
import altair as alt
import pandas as pd

SELECTION = "tradeoff_group"


def tradeoff_chart(points):
    """미확인 비용을 별도 고정 크기 점으로 그려 null size 누락을 막는다."""
    tooltip = ["그룹:N", "방어 조건:N", "데이터 출처:N", "데이터 구분:N", "추천 판단:N", "표본:N",
               alt.Tooltip("정상 태스크 성공률:Q", format=".1%"),
               alt.Tooltip("공격 차단율 (1-ASR):Q", format=".1%"),
               "ASR 95% CI:N", "공격 차단율 95% CI:N", "정상 성공률 95% CI:N", "공격 평가 수:Q", "정상 평가 수:Q",
               "공격 family 수:Q", "정상 family 수:Q", "비용 표시:N", "비용 상태:N",
               "평가 상태:N", "공격 평가 제외:N", "정상 평가 제외:N",
               "정상 기준:N", "정상 기준 공유 범위:N", "정상 기준 실행 번호:N", "비용 범위:N",
               "정상 기준 평가 완료:N", "정상 기준 평가/계획:N", "정상 기준 제외 수:N",
               "대표 실행 번호:N", "같은 자리 그룹:N"]

    def base(rows):
        return alt.Chart(pd.DataFrame(rows)).encode(
            x=alt.X("정상 태스크 성공률:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
            y=alt.Y("공격 차단율 (1-ASR):Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
            color=alt.Color("방어 조건:N"), shape=alt.Shape("앱:N"),
            opacity=alt.Opacity("표본:N", scale=alt.Scale(domain=["CI 계산됨", "표본 부족"], range=[0.9, 0.35])),
            tooltip=tooltip,
        )

    known = [point for point in points if point["요청당 비용"] is not None]
    unknown = [point for point in points if point["요청당 비용"] is None]
    layers = []
    if known:
        layers.append(base(known).mark_point(filled=True).encode(
            size=alt.Size("요청당 비용:Q", scale=alt.Scale(range=[80, 600], zero=True))))
    if unknown:
        layers.append(base(unknown).mark_point(filled=False, size=140, strokeWidth=2))
    chart = alt.layer(*layers)
    return chart.add_params(alt.selection_point(name=SELECTION, fields=["group_id"], toggle=False))


def selected_group(event, group_ids):
    """차트 이벤트의 공개 group_id만 허용한다."""
    selection = event.get("selection", {}) if isinstance(event, dict) else {}
    if not isinstance(selection, dict):
        return None
    rows = selection.get(SELECTION) or []
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        value = rows[0].get("group_id")
        if value in group_ids:
            return value
    return None
