"""
구간 8 (BP2L → busLR) PV2 2MW 연계 전후 비교 시뮬레이션
"""

import opendssdirect as dss
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

from plot_utils import set_korean_font

set_korean_font()

# ── 공통 회로 (PV2 제외) ──────────────────────────────────────────────────────

BASE_SCRIPT = """
Clear
New Circuit.KR_Feeder
~ basekv=154 pu=1.0 phases=3 bus1=sourcebus
~ Isc3=20000 Isc1=21000

New Transformer.T_SUB phases=3 windings=2
~ wdg=1 bus=sourcebus kv=154  kva=60000 %r=0.3 X=12
~ wdg=2 bus=bus1      kv=22.9 kva=60000 %r=0.3

New LineCode.main r1=0.192 x1=0.361 r0=0.576 x0=1.08 units=km
New LineCode.sub  r1=0.320 x1=0.380 r0=0.960 x0=1.14 units=km

New Line.L_main1 bus1=bus1  bus2=bus2  linecode=main length=1.0
New Line.L_main2 bus1=bus2  bus2=bp1   linecode=main length=1.5
New Line.L_left1 bus1=bp1   bus2=busL1 linecode=sub  length=2.0
New Line.L_left2 bus1=busL1 bus2=bp2L  linecode=sub  length=1.5
New Line.L_LL    bus1=bp2L  bus2=busLL linecode=sub  length=2.5
New Line.L_LR    bus1=bp2L  bus2=busLR linecode=sub  length=2.0
New Line.L_right1 bus1=bp1   bus2=busR1 linecode=sub  length=2.0
New Line.L_right2 bus1=busR1 bus2=bp2R  linecode=sub  length=1.8
New Line.L_RL    bus1=bp2R  bus2=busRL linecode=sub  length=2.2
New Line.L_RR    bus1=bp2R  bus2=busRR linecode=sub  length=1.5

New Load.Load_A  bus1=bus1  phases=3 kv=22.9 kw=1500 kvar=680 model=1
New Load.Load_B  bus1=bus2  phases=3 kv=22.9 kw=2000 kvar=900 model=1
New Load.Load_C  bus1=busL1 phases=3 kv=22.9 kw=1200 kvar=540 model=1
New Load.Load_LL bus1=busLL phases=3 kv=22.9 kw=1800 kvar=810 model=1
New Load.Load_LR bus1=busLR phases=3 kv=22.9 kw=900  kvar=400 model=1
New Load.Load_D  bus1=busR1 phases=3 kv=22.9 kw=1400 kvar=630 model=1
New Load.Load_RL bus1=busRL phases=3 kv=22.9 kw=2000 kvar=900 model=1
New Load.Load_RR bus1=busRR phases=3 kv=22.9 kw=1300 kvar=590 model=1

New PVSystem.PV1 bus1=busL1 phases=3 kv=22.9 kva=1100 pmpp=1000 irradiance=1.0 pf=1.0
New PVSystem.PV3 bus1=busR1 phases=3 kv=22.9 kva=1650 pmpp=1500 irradiance=1.0 pf=1.0
New PVSystem.PV4 bus1=busRR phases=3 kv=22.9 kva=550  pmpp=500  irradiance=1.0 pf=1.0

Set voltagebases=[154, 22.9]
Calcvoltagebases
"""

PV2_SCRIPT = """
New PVSystem.PV2 bus1=busLR phases=3 kv=22.9 kva=2200 pmpp=2000 irradiance=1.0 pf=1.0
"""

BUS_ORDER = ["bus1", "bus2", "bp1",
             "busL1", "bp2L", "busLL", "busLR",
             "busR1", "bp2R", "busRL", "busRR"]

BUS_LABELS = ["접속점1", "접속점2", "분기점1",
              "좌측1", "분기점2(좌)", "좌-좌말단", "좌-우말단\n(Section8 말단)",
              "우측1", "분기점2(우)", "우-좌말단", "우-우말단"]

# 구간 8에 해당하는 선로
SEG8_LINE = "L_LR"


def get_bus_voltages():
    bus_v = {}
    for bus in BUS_ORDER:
        dss.Circuit.SetActiveBus(bus)
        v_pu = dss.Bus.puVmagAngle()
        phases = len(v_pu) // 2
        bus_v[bus] = np.mean([v_pu[i * 2] for i in range(phases)]) if phases else 0
    return [bus_v[b] for b in BUS_ORDER]


def get_line_power(line_name):
    """선로의 유효전력/무효전력/전류 반환 (송전단 기준, kW/kvar/A)."""
    dss.Lines.Name(line_name)
    powers = dss.CktElement.Powers()   # [P1,Q1, P2,Q2, P3,Q3, ...]
    # 3상 합산 (송전단 = 처음 6개)
    p = sum(powers[i]     for i in range(0, 6, 2))
    q = sum(powers[i + 1] for i in range(0, 6, 2))
    currents = dss.CktElement.CurrentsMagAng()
    i_mag = np.mean([currents[i] for i in range(0, 6, 2)])
    return p, q, i_mag


def run_case(with_pv2: bool):
    script = BASE_SCRIPT + (PV2_SCRIPT if with_pv2 else "")
    dss.run_command(script)
    dss.run_command("Solve mode=snap")

    voltages = get_bus_voltages()
    p_seg8, q_seg8, i_seg8 = get_line_power(SEG8_LINE)
    total = dss.Circuit.TotalPower()

    pv2_kw = 0.0
    if with_pv2:
        dss.PVsystems.Name("pv2")
        pv2_kw = dss.PVsystems.kW()

    return {
        "voltages": voltages,
        "seg8_p_kw": p_seg8,
        "seg8_q_kvar": q_seg8,
        "seg8_i_a": i_seg8,
        "total_p_kw": -total[0],
        "pv2_kw": pv2_kw,
    }


def irradiance_sweep_pv2():
    """PV2 일사량 0→1 스윕: 구간8 전력/전류 및 busLR 전압 변화."""
    irr_levels = np.linspace(0, 1.0, 21)
    seg8_p, seg8_i, v_busLR = [], [], []

    for irr in irr_levels:
        dss.run_command(BASE_SCRIPT + PV2_SCRIPT)
        dss.run_command(f"PVSystem.PV2.irradiance={irr}")
        dss.run_command("Solve mode=snap")

        p, _, i_mag = get_line_power(SEG8_LINE)
        seg8_p.append(p)
        seg8_i.append(i_mag)

        dss.Circuit.SetActiveBus("busLR")
        v = dss.Bus.puVmagAngle()
        v_busLR.append(np.mean([v[i * 2] for i in range(len(v) // 2)]))

    return irr_levels, seg8_p, seg8_i, v_busLR


# ── 실행 ──────────────────────────────────────────────────────────────────────

print(">>> PV2 없음 계산...")
no_pv2 = run_case(with_pv2=False)

print(">>> PV2 있음 (2MW) 계산...")
with_pv2 = run_case(with_pv2=True)

print(">>> PV2 일사량 스윕 중...")
irr_levels, seg8_p_sweep, seg8_i_sweep, v_busLR_sweep = irradiance_sweep_pv2()

# ── 결과 출력 ─────────────────────────────────────────────────────────────────

print("\n" + "=" * 62)
print("  Section 8 (분기점2(좌) → 좌-우말단)  PV2 연계 전후 비교")
print("=" * 62)
print(f"{'항목':<30} {'PV2 없음':>14} {'PV2 2MW':>14}")
print("-" * 62)
print(f"{'Section8 유효전력 [kW]':<30} {no_pv2['seg8_p_kw']:>14.1f} {with_pv2['seg8_p_kw']:>14.1f}")
print(f"{'Section8 무효전력 [kvar]':<29} {no_pv2['seg8_q_kvar']:>14.1f} {with_pv2['seg8_q_kvar']:>14.1f}")
print(f"{'Section8 평균 전류 [A]':<30} {no_pv2['seg8_i_a']:>14.1f} {with_pv2['seg8_i_a']:>14.1f}")
print(f"{'좌-우말단 전압 [pu]':<30} {no_pv2['voltages'][6]:>14.4f} {with_pv2['voltages'][6]:>14.4f}")
print(f"{'계통 수전 전력 [kW]':<30} {no_pv2['total_p_kw']:>14.1f} {with_pv2['total_p_kw']:>14.1f}")
print("=" * 62)

# ── 그래프 ────────────────────────────────────────────────────────────────────

fig = plt.figure(figsize=(13, 9))
fig.suptitle("Section 8 (분기점2(좌) → 좌-우말단)  PV2 2MW 연계 전후 비교", fontsize=14, fontweight="bold")
gs = gridspec.GridSpec(2, 3, figure=fig, hspace=0.45, wspace=0.38)

x = np.arange(len(BUS_ORDER))
colors = {"no": "#4dabf7", "pv": "#f03e3e"}

# ── (1) 전체 모선 전압 프로파일 비교 ──────────────────────────────────────────
ax1 = fig.add_subplot(gs[0, :2])
ax1.plot(x, no_pv2["voltages"],   "o-", color=colors["no"], lw=2, ms=6, label="PV2 없음")
ax1.plot(x, with_pv2["voltages"], "s-", color=colors["pv"], lw=2, ms=6, label="PV2 2MW")
ax1.axvline(x=6, color="gray", ls=":", lw=1.5, label="좌-우말단 (Section8 말단)")
ax1.axhline(1.05, color="orange", ls="--", lw=1, label="상한 1.05pu")
ax1.axhline(0.95, color="purple", ls="--", lw=1, label="하한 0.95pu")
ax1.set_xticks(x)
ax1.set_xticklabels(BUS_LABELS, rotation=40, ha="right", fontsize=8)
ax1.set_ylabel("전압 [pu]")
ax1.set_title("전체 모선 전압 프로파일")
ax1.set_ylim(0.92, 1.06)
ax1.legend(fontsize=8, loc="lower left")
ax1.grid(True, alpha=0.3)

# 전압 차이 강조
for i, (v_no, v_pv) in enumerate(zip(no_pv2["voltages"], with_pv2["voltages"])):
    if abs(v_pv - v_no) > 0.0005:
        ax1.annotate(f"+{(v_pv-v_no)*1000:.1f}m",
                     xy=(i, v_pv), xytext=(i, v_pv + 0.003),
                     ha="center", fontsize=7, color="#e03131")

# ── (2) busLR 전압 vs 일사량 ───────────────────────────────────────────────
ax2 = fig.add_subplot(gs[0, 2])
ax2.axhline(no_pv2["voltages"][6], color=colors["no"], ls="--", lw=1.5, label=f"PV2 없음 {no_pv2['voltages'][6]:.4f}pu")
ax2.plot(irr_levels, v_busLR_sweep, "s-", color=colors["pv"], lw=2, ms=5, label="PV2 있음")
ax2.axhline(1.05, color="orange", ls="--", lw=1)
ax2.axhline(0.95, color="purple", ls="--", lw=1)
ax2.set_xlabel("PV2 일사량 [pu]")
ax2.set_ylabel("전압 [pu]")
ax2.set_title("좌-우말단 전압 변화\n(일사량에 따라)")
ax2.set_ylim(0.92, 1.06)
ax2.legend(fontsize=7)
ax2.grid(True, alpha=0.3)

# ── (3) 구간⑧ 유효전력 비교 막대 ─────────────────────────────────────────────
ax3 = fig.add_subplot(gs[1, 0])
bars = ax3.bar(["PV2 없음", "PV2 2MW"],
               [no_pv2["seg8_p_kw"], with_pv2["seg8_p_kw"]],
               color=[colors["no"], colors["pv"]], edgecolor="white", width=0.5)
for bar, val in zip(bars, [no_pv2["seg8_p_kw"], with_pv2["seg8_p_kw"]]):
    ax3.text(bar.get_x() + bar.get_width() / 2,
             bar.get_height() + 5, f"{val:.0f} kW",
             ha="center", va="bottom", fontsize=10, fontweight="bold")
ax3.set_ylabel("유효전력 [kW]")
ax3.set_title("Section8 유효전력\n(분기점2(좌)→좌-우말단)")
ax3.grid(True, alpha=0.3, axis="y")

# ── (4) 구간⑧ 전류 비교 막대 ──────────────────────────────────────────────────
ax4 = fig.add_subplot(gs[1, 1])
bars = ax4.bar(["PV2 없음", "PV2 2MW"],
               [no_pv2["seg8_i_a"], with_pv2["seg8_i_a"]],
               color=[colors["no"], colors["pv"]], edgecolor="white", width=0.5)
for bar, val in zip(bars, [no_pv2["seg8_i_a"], with_pv2["seg8_i_a"]]):
    ax4.text(bar.get_x() + bar.get_width() / 2,
             bar.get_height() + 0.3, f"{val:.1f} A",
             ha="center", va="bottom", fontsize=10, fontweight="bold")
ax4.set_ylabel("전류 [A]")
ax4.set_title("Section8 평균 전류")
ax4.grid(True, alpha=0.3, axis="y")

# ── (5) 구간⑧ 전력/전류 vs 일사량 ────────────────────────────────────────────
ax5 = fig.add_subplot(gs[1, 2])
ax5_twin = ax5.twinx()
ax5.plot(irr_levels, seg8_p_sweep, "o-", color="#2f9e44", lw=2, ms=4, label="유효전력 [kW]")
ax5_twin.plot(irr_levels, seg8_i_sweep, "s--", color="#e67700", lw=2, ms=4, label="전류 [A]")
ax5.axhline(no_pv2["seg8_p_kw"], color="#4dabf7", ls=":", lw=1.5, label=f"PV2 없을 때 ({no_pv2['seg8_p_kw']:.0f}kW)")
ax5.set_xlabel("PV2 일사량 [pu]")
ax5.set_ylabel("유효전력 [kW]", color="#2f9e44")
ax5_twin.set_ylabel("전류 [A]", color="#e67700")
ax5.set_title("Section8 전력·전류 변화\n(일사량에 따라)")
lines1, labels1 = ax5.get_legend_handles_labels()
lines2, labels2 = ax5_twin.get_legend_handles_labels()
ax5.legend(lines1 + lines2, labels1 + labels2, fontsize=7, loc="upper right")
ax5.grid(True, alpha=0.3)

plt.tight_layout(rect=[0, 0, 1, 0.96])
plt.savefig("segment8_comparison.png", dpi=150, bbox_inches="tight")
print("\n결과 저장: segment8_comparison.png")
plt.show()
