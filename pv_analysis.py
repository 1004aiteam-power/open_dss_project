"""
한국 22.9kV 배전 피더 - 태양광 연계 시뮬레이션

네트워크 구조 (그림 기반):
  154kV 변전소
      │
    bus1 ── 고압고객A (변전소 직후)
      │
    bus2 ── 고압고객B
      │
   BP1 (Branch Point 1)
   /              \
 busL1            busR1
 (고압고객C, PV1)  (고압고객D, PV3)
   │                │
  BP2L            BP2R
  /    \          /    \
busLL  busLR   busRL  busRR
(부하) (부하,  (부하)  (부하,
       PV2)           PV4)
"""

import opendssdirect as dss
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.font_manager as fm

# macOS 한글 폰트 설정
_kor_fonts = [f.name for f in fm.fontManager.ttflist if "AppleGothic" in f.name or "NanumGothic" in f.name]
if _kor_fonts:
    plt.rcParams["font.family"] = _kor_fonts[0]
plt.rcParams["axes.unicode_minus"] = False

# ── DSS 회로 정의 ─────────────────────────────────────────────────────────────

DSS_SCRIPT = """
Clear

! ── 154kV 전원 (송전계통 연결점) ─────────────────────────────────────────────
New Circuit.KR_Feeder
~ basekv=154 pu=1.0 phases=3 bus1=sourcebus
~ Isc3=20000 Isc1=21000

! ── 변전소 주변압기 154kV → 22.9kV, 60MVA ────────────────────────────────────
New Transformer.T_SUB phases=3 windings=2
~ wdg=1 bus=sourcebus kv=154  kva=60000 %r=0.3 X=12
~ wdg=2 bus=bus1      kv=22.9 kva=60000 %r=0.3

! ── 선로 코드 (ACSR 가공선, 한국 배전 기준) ──────────────────────────────────
! main : ACSR 160mm² - 간선
! sub  : ACSR  95mm² - 분기선
New LineCode.main r1=0.192 x1=0.361 r0=0.576 x0=1.08 units=km
New LineCode.sub  r1=0.320 x1=0.380 r0=0.960 x0=1.14 units=km

! ── 선로 구성 ────────────────────────────────────────────────────────────────
! 변전소 → bus1 → bus2 → BP1 (간선)
New Line.L_main1 bus1=bus1 bus2=bus2  linecode=main length=1.0
New Line.L_main2 bus1=bus2 bus2=bp1   linecode=main length=1.5

! BP1 → 왼쪽 가지 → busL1 → BP2L
New Line.L_left1  bus1=bp1   bus2=busL1  linecode=sub length=2.0
New Line.L_left2  bus1=busL1 bus2=bp2L   linecode=sub length=1.5

! BP2L → 말단 왼쪽-왼쪽, 왼쪽-오른쪽
New Line.L_LL bus1=bp2L bus2=busLL linecode=sub length=2.5
New Line.L_LR bus1=bp2L bus2=busLR linecode=sub length=2.0

! BP1 → 오른쪽 가지 → busR1 → BP2R
New Line.L_right1 bus1=bp1   bus2=busR1  linecode=sub length=2.0
New Line.L_right2 bus1=busR1 bus2=bp2R   linecode=sub length=1.8

! BP2R → 말단 오른쪽-왼쪽, 오른쪽-오른쪽
New Line.L_RL bus1=bp2R bus2=busRL linecode=sub length=2.2
New Line.L_RR bus1=bp2R bus2=busRR linecode=sub length=1.5

! ── 고압고객 부하 (22.9kV 직접 수전) ─────────────────────────────────────────
! 변전소 직후
New Load.Load_A bus1=bus1  phases=3 kv=22.9 kw=1500 kvar=680 model=1

! 간선 중간
New Load.Load_B bus1=bus2  phases=3 kv=22.9 kw=2000 kvar=900 model=1

! 왼쪽 가지
New Load.Load_C  bus1=busL1 phases=3 kv=22.9 kw=1200 kvar=540 model=1
New Load.Load_LL bus1=busLL phases=3 kv=22.9 kw=1800 kvar=810 model=1
New Load.Load_LR bus1=busLR phases=3 kv=22.9 kw=900  kvar=400 model=1

! 오른쪽 가지
New Load.Load_D  bus1=busR1 phases=3 kv=22.9 kw=1400 kvar=630 model=1
New Load.Load_RL bus1=busRL phases=3 kv=22.9 kw=2000 kvar=900 model=1
New Load.Load_RR bus1=busRR phases=3 kv=22.9 kw=1300 kvar=590 model=1

! ── PV 시스템 (22.9kV 배전선로 직접 연계) ────────────────────────────────────
! PV1 - 왼쪽 가지 busL1 (1MW)
New PVSystem.PV1 bus1=busL1 phases=3 kv=22.9 kva=1100 pmpp=1000
~ irradiance=1.0 pf=1.0

! PV2 - 왼쪽 말단 busLR (2MW)
New PVSystem.PV2 bus1=busLR phases=3 kv=22.9 kva=2200 pmpp=2000
~ irradiance=1.0 pf=1.0

! PV3 - 오른쪽 가지 busR1 (1.5MW)
New PVSystem.PV3 bus1=busR1 phases=3 kv=22.9 kva=1650 pmpp=1500
~ irradiance=1.0 pf=1.0

! PV4 - 오른쪽 말단 busRR (0.5MW)
New PVSystem.PV4 bus1=busRR phases=3 kv=22.9 kva=550 pmpp=500
~ irradiance=1.0 pf=1.0

Set voltagebases=[154, 22.9]
Calcvoltagebases
"""

# 버스 순서 (22.9kV 배전측만, 피더 흐름 순서대로)
BUS_ORDER = ["bus1", "bus2", "bp1",
             "busL1", "bp2L", "busLL", "busLR",
             "busR1", "bp2R", "busRL", "busRR"]

BUS_LABELS = ["접속점1\n(고압A)", "접속점2\n(고압B)", "분기점1",
              "좌측1\n(고압C,PV1)", "분기점2(좌)", "좌-좌말단\n(고압)", "좌-우말단\n(고압,PV2)",
              "우측1\n(고압D,PV3)", "분기점2(우)", "우-좌말단\n(고압)", "우-우말단\n(고압,PV4)"]

PV_NAMES = ["PV1", "PV2", "PV3", "PV4"]


def run_power_flow(irradiance: float = 1.0) -> dict:
    dss.run_command(DSS_SCRIPT)
    for pv in PV_NAMES:
        dss.run_command(f"PVSystem.{pv}.irradiance={irradiance}")
    dss.run_command("Solve mode=snap")

    # 버스 전압 수집
    all_buses = dss.Circuit.AllBusNames()
    bus_v = {}
    for bus in all_buses:
        dss.Circuit.SetActiveBus(bus)
        v_pu = dss.Bus.puVmagAngle()
        phases = len(v_pu) // 2
        bus_v[bus] = np.mean([v_pu[i * 2] for i in range(phases)]) if phases else 0

    voltages = [bus_v.get(b, 0) for b in BUS_ORDER]

    total_power = dss.Circuit.TotalPower()

    pv_output = {}
    dss.PVsystems.First()
    while True:
        name = dss.PVsystems.Name()
        pv_output[name] = dss.PVsystems.kW()
        if not dss.PVsystems.Next():
            break

    return {
        "buses": BUS_ORDER,
        "voltages": voltages,
        "total_p_kw": -total_power[0],
        "total_q_kvar": -total_power[1],
        "pv_output": pv_output,
    }


def irradiance_sweep():
    irr_levels = np.linspace(0, 1.0, 21)
    total_p_list, pv_totals = [], []
    voltage_profiles = {b: [] for b in BUS_ORDER}

    for irr in irr_levels:
        result = run_power_flow(irr)
        total_p_list.append(result["total_p_kw"])
        pv_totals.append(sum(result["pv_output"].values()))
        for b, v in zip(result["buses"], result["voltages"]):
            voltage_profiles[b].append(v)

    return irr_levels, total_p_list, pv_totals, voltage_profiles


def plot_results(base, full_pv, irr_levels, total_p_list, pv_totals, voltage_profiles):
    fig = plt.figure(figsize=(13, 9))
    fig.suptitle("한국 22.9kV 배전 피더 - 태양광 연계 분석", fontsize=14, fontweight="bold", y=0.99)
    gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.5, wspace=0.35)

    x = np.arange(len(BUS_ORDER))

    # ── (1) 전압 프로파일 ─────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(x, base["voltages"],    "b-o", label="PV 없음",    markersize=5)
    ax1.plot(x, full_pv["voltages"], "r-s", label="PV 전체출력", markersize=5)
    ax1.axhline(1.05, color="orange", ls="--", lw=1, label="상한 1.05pu")
    ax1.axhline(0.95, color="purple", ls="--", lw=1, label="하한 0.95pu")
    ax1.set_xticks(x)
    ax1.set_xticklabels(BUS_LABELS, rotation=60, ha="right", fontsize=7)
    ax1.set_ylabel("전압 [pu]")
    ax1.set_title("모선별 전압 프로파일")
    ax1.legend(fontsize=8)
    ax1.set_ylim(0.88, 1.10)
    ax1.grid(True, alpha=0.3)

    # ── (2) 일사량에 따른 전력 변화 ──────────────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.plot(irr_levels, total_p_list, "g-o", markersize=5, label="계통 공급 전력")
    ax2.plot(irr_levels, pv_totals,    "r-s", markersize=5, label="PV 총 발전량")
    ax2.set_xlabel("일사량 [pu]")
    ax2.set_ylabel("전력 [kW]")
    ax2.set_title("일사량에 따른 전력 변화")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    # ── (3) PV별 발전량 ───────────────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 0])
    pv_names = list(full_pv["pv_output"].keys())
    pv_kw    = [full_pv["pv_output"][n] for n in pv_names]
    pv_locs  = ["busL1", "busLR", "busR1", "busRR"]
    colors   = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4"]
    bars = ax3.bar([f"{n}\n({loc})" for n, loc in zip(pv_names, pv_locs)],
                   pv_kw, color=colors, edgecolor="white", linewidth=1.2)
    for bar, val in zip(bars, pv_kw):
        ax3.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 5,
                 f"{val/1000:.1f}MW", ha="center", va="bottom", fontsize=9)
    ax3.set_ylabel("출력 [kW]")
    ax3.set_title("PV 시스템별 발전량 (일사량 100%)")
    ax3.grid(True, alpha=0.3, axis="y")

    # ── (4) PV 연계 모선 전압 변화 ────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[1, 1])
    key_buses  = ["busL1", "busLR", "busR1", "busRR"]
    key_labels = ["좌측1(PV1)", "좌-우말단(PV2)", "우측1(PV3)", "우-우말단(PV4)"]
    cmap = plt.get_cmap("tab10")
    for i, (bus, label) in enumerate(zip(key_buses, key_labels)):
        ax4.plot(irr_levels, voltage_profiles[bus],
                 "-o", markersize=4, color=cmap(i), label=label)
    ax4.axhline(1.05, color="orange", ls="--", lw=1)
    ax4.axhline(0.95, color="purple", ls="--", lw=1)
    ax4.set_xlabel("일사량 [pu]")
    ax4.set_ylabel("전압 [pu]")
    ax4.set_title("PV 연계 모선 전압 변화")
    ax4.legend(fontsize=8)
    ax4.set_ylim(0.88, 1.10)
    ax4.grid(True, alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    plt.savefig("pv_analysis_result.png", dpi=150, bbox_inches="tight")
    print("결과 저장: pv_analysis_result.png")
    plt.show()


def print_summary(base, full_pv):
    print("\n" + "=" * 58)
    print("  한국 22.9kV 배전 피더 - PV 연계 전후 비교")
    print("=" * 58)
    print(f"{'항목':<28} {'PV 없음':>12} {'PV 전체출력':>12}")
    print("-" * 58)
    print(f"{'계통 공급 유효전력 [kW]':<28} {base['total_p_kw']:>12.1f} {full_pv['total_p_kw']:>12.1f}")
    print(f"{'계통 공급 무효전력 [kvar]':<27} {base['total_q_kvar']:>12.1f} {full_pv['total_q_kvar']:>12.1f}")
    valid_base = [v for v in base["voltages"] if v > 0.1]
    valid_pv   = [v for v in full_pv["voltages"] if v > 0.1]
    print(f"{'최저 전압 [pu]':<28} {min(valid_base):>12.4f} {min(valid_pv):>12.4f}")
    print(f"{'최고 전압 [pu]':<28} {max(valid_base):>12.4f} {max(valid_pv):>12.4f}")
    total_pv   = sum(full_pv["pv_output"].values())
    reduction  = base["total_p_kw"] - full_pv["total_p_kw"]
    print("-" * 58)
    print(f"{'총 PV 발전량 [kW]':<28} {'':>12} {total_pv:>12.1f}")
    print(f"{'계통 수전 감소량 [kW]':<28} {'':>12} {reduction:>12.1f}")
    print("=" * 58)
    print("\n[PV 시스템별 출력]")
    for name, kw in full_pv["pv_output"].items():
        print(f"  {name}: {kw/1000:.2f} MW")


if __name__ == "__main__":
    print(">>> PV 없음 조류 계산...")
    base_result = run_power_flow(irradiance=0.0)

    print(">>> PV 전체 출력(일사량 100%) 조류 계산...")
    full_pv_result = run_power_flow(irradiance=1.0)

    print(">>> 일사량 스윕 분석 중...")
    irr_levels, total_p_list, pv_totals, voltage_profiles = irradiance_sweep()

    print_summary(base_result, full_pv_result)

    print("\n>>> 결과 시각화...")
    plot_results(base_result, full_pv_result, irr_levels, total_p_list, pv_totals, voltage_profiles)
