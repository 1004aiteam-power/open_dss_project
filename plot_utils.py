"""
matplotlib 한글 폰트 설정 공통 유틸
pv_analysis.py, segment8_pv_comparison.py 에서 공유
"""
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

# OS별 대표 한글 폰트 후보 (우선순위 순)
KOREAN_FONT_CANDIDATES = [
    "AppleGothic", "AppleSDGothicNeo",     # macOS
    "Malgun Gothic",                       # Windows
    "NanumGothic", "NanumBarunGothic",     # Linux (나눔글꼴)
    "Noto Sans CJK KR", "Noto Sans KR",    # Linux (Noto)
    "UnDotum", "UnBatang",                 # Linux (은글꼴)
]


def set_korean_font():
    """설치된 폰트 중 한글 지원 폰트를 찾아 matplotlib 기본 폰트로 설정한다.
    지원 폰트를 찾지 못하면 경고를 출력하고 기본 폰트를 그대로 둔다."""
    installed = {f.name for f in fm.fontManager.ttflist}
    plt.rcParams["axes.unicode_minus"] = False

    for candidate in KOREAN_FONT_CANDIDATES:
        if candidate in installed:
            plt.rcParams["font.family"] = candidate
            return candidate

    print("[경고] 한글 폰트를 찾지 못했습니다. 그래프의 한글 라벨이 깨져 보일 수 있습니다.")
    return None
