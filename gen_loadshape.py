"""
OpenDSS LoadShape 생성기 — 8760시간 부하 / 태양광 출력 프로파일

출력:
  load_8760.csv : 부하 배율 (연중 최대부하 = 1.0)
  pv_8760.csv   : 태양광 출력 배율 (설비용량 대비)

가상 데이터입니다. 실계통 실적이 아니며 패턴 재현이 목적입니다.
실적 데이터가 있으면 반드시 교체해서 쓰십시오.
"""

import numpy as np
import csv
import datetime

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
YEAR = 2025
LAT = 36.5                    # 위도 (한국 중부 기준)
SEED = 42                     # 재현성 확보용

rng = np.random.default_rng(SEED)


# ─────────────────────────────────────────────
# 1. 부하 프로파일
# ─────────────────────────────────────────────
def hourly_load_shape(is_weekend, month):
    """24시간 부하 형상. 여름/겨울은 냉난방으로 주간 피크가 커짐."""
    # 기본 형상 (0~23시)
    base = np.array([
        0.62, 0.58, 0.55, 0.54, 0.55, 0.58,   # 0-5
        0.65, 0.74, 0.84, 0.92, 0.96, 0.98,   # 6-11
        0.95, 0.97, 1.00, 0.99, 0.96, 0.93,   # 12-17
        0.92, 0.90, 0.86, 0.80, 0.73, 0.67,   # 18-23
    ])
    if is_weekend:
        # 주말은 산업부하가 빠져 주간 피크가 눌림
        base = base * np.array([
            1.00, 1.00, 1.00, 1.00, 1.00, 1.00,
            0.95, 0.88, 0.80, 0.75, 0.73, 0.72,
            0.72, 0.72, 0.73, 0.74, 0.76, 0.80,
            0.86, 0.90, 0.90, 0.88, 0.86, 0.84,
        ])
    return base


def monthly_factor(month):
    """월별 부하 수준. 7~8월 냉방, 12~1월 난방 피크."""
    table = {
        1: 0.95, 2: 0.90, 3: 0.80, 4: 0.72,
        5: 0.72, 6: 0.85, 7: 0.98, 8: 1.00,
        9: 0.84, 10: 0.73, 11: 0.80, 12: 0.93,
    }
    return table[month]


def build_load():
    out = []
    d = datetime.datetime(YEAR, 1, 1)
    for h in range(8760):
        is_weekend = d.weekday() >= 5
        shape = hourly_load_shape(is_weekend, d.month)
        v = shape[d.hour] * monthly_factor(d.month)
        v *= 1.0 + rng.normal(0, 0.02)          # 일간 변동
        out.append(max(v, 0.05))
        d += datetime.timedelta(hours=1)
    arr = np.array(out)
    return arr / arr.max()                       # 최대 = 1.0 정규화


# ─────────────────────────────────────────────
# 2. 태양광 출력 프로파일
# ─────────────────────────────────────────────
def clear_sky(doy, hour):
    """맑은 날 기준 정규화 출력 (0~1). 태양고도 기반 근사."""
    decl = 23.45 * np.sin(np.radians(360 * (284 + doy) / 365))
    ha = 15 * (hour + 0.5 - 12)                  # 시간각
    alt = np.degrees(np.arcsin(
        np.sin(np.radians(LAT)) * np.sin(np.radians(decl)) +
        np.cos(np.radians(LAT)) * np.cos(np.radians(decl)) *
        np.cos(np.radians(ha))
    ))
    if alt <= 0:
        return 0.0
    return float(np.sin(np.radians(alt)) ** 1.2)


def build_pv(peak_ratio=0.82):
    """
    peak_ratio: 맑은 날 정오 최대 출력 / 설비용량
                (인버터 손실, 온도 저감, 각도 손실 반영)
    """
    out = []
    d = datetime.datetime(YEAR, 1, 1)
    day_cloud = None
    last_day = -1

    for h in range(8760):
        doy = d.timetuple().tm_yday
        if doy != last_day:
            # 일 단위 날씨 (맑음 0.85~1.0, 흐림 0.15~0.5)
            day_cloud = rng.choice([1.0, 0.72, 0.35, 0.12],
                                   p=[0.42, 0.24, 0.20, 0.14])
            last_day = doy

        v = clear_sky(doy, d.hour) * peak_ratio * day_cloud
        if v > 0:
            v *= 1.0 + rng.normal(0, 0.06)       # 시간별 구름 변동
        out.append(float(np.clip(v, 0, 1.0)))
        d += datetime.timedelta(hours=1)

    return np.array(out)


# ─────────────────────────────────────────────
# 3. 저장 및 요약
# ─────────────────────────────────────────────
def save(path, arr):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        for v in arr:
            w.writerow([round(float(v), 5)])


def summarize(load, pv):
    d0 = datetime.datetime(YEAR, 1, 1)
    hours = [d0 + datetime.timedelta(hours=i) for i in range(8760)]

    print(f"부하  최대 {load.max():.3f} / 최소 {load.min():.3f} / 평균 {load.mean():.3f}")
    print(f"태양광 최대 {pv.max():.3f} / 이용률 {pv.mean()*100:.1f}%")

    # 태양광 출력 시간대(10~15시) 최소부하 — 역조류 최악 조건
    mask = np.array([10 <= t.hour <= 15 for t in hours])
    idx = np.where(mask)[0]
    worst = idx[np.argmin(load[idx] / np.maximum(pv[idx], 1e-6))]
    print(f"\n[역조류 최악 조건]")
    print(f"  시점   {hours[worst]:%Y-%m-%d %H시} ({'토일'[hours[worst].weekday()-5] if hours[worst].weekday()>=5 else '평일'})")
    print(f"  부하   {load[worst]:.3f}")
    print(f"  태양광 {pv[worst]:.3f}")
    print(f"  비율   태양광/부하 = {pv[worst]/load[worst]:.2f}")


if __name__ == "__main__":
    load = build_load()
    pv = build_pv()
    save("load_8760.csv", load)
    save("pv_8760.csv", pv)
    summarize(load, pv)
    print("\n생성 완료: load_8760.csv, pv_8760.csv")
