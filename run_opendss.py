"""
Neo4j CIM → OpenDSS Power Flow 시뮬레이션
두 배전선로(피더1: 이진트리, 피더2: 빗살) 동시 해석
"""
import opendssdirect as dss
from neo4j import GraphDatabase
from pathlib import Path

from network_model import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, fetch_network, build_dss_script

OUT_DIR = Path(__file__).parent / "dss_output"
OUT_DIR.mkdir(exist_ok=True)


# ── DSS 스크립트 생성 및 저장 ──────────────────────────────────

def build_dss(sub, lines, loads, pvs, cbs):
    script = build_dss_script(sub, lines, loads, pvs, cbs,
                               pv_irradiance=0.5, mode="snapshot", export_dir=OUT_DIR)
    dss_file = OUT_DIR / "korean_dist.dss"
    dss_file.write_text(script, encoding="utf-8")
    print(f"[DSS] 스크립트 저장: {dss_file}")
    return str(dss_file)


# ── 3. OpenDSS 실행 및 결과 출력 ─────────────────────────────

def run_and_report(dss_file):
    dss.run_command(f'Redirect "{dss_file}"')

    if not dss.Solution.Converged():
        print("⚠️  해 수렴 실패 — 회로 구성을 확인하세요.")
        print("   에러:", dss.Error.Description())
        return

    print("\n" + "="*60)
    print("  OpenDSS Power Flow 결과  (22.9kV 배전망)")
    print("="*60)

    # ── 모선 전압 ──
    print("\n📍 모선 전압 [pu]")
    print(f"  {'버스':<30} {'Va':>8} {'Vb':>8} {'Vc':>8}")
    print("  " + "-"*58)

    dss.Circuit.SetActiveBus("")  # reset
    bus_names = dss.Circuit.AllBusNames()
    bus_volts = dss.Circuit.AllBusMagPu()

    # AllBusMagPu: 각 버스의 노드별 pu 값 (3상이면 3개)
    # 버스당 노드 수가 다를 수 있으므로 순서대로 끊어서 읽음
    idx = 0
    bus_result = {}
    for bname in bus_names:
        dss.Circuit.SetActiveBus(bname)
        n = dss.Bus.NumNodes()
        vals = bus_volts[idx:idx+n]
        idx += n
        avg = sum(vals)/len(vals) if vals else 0
        bus_result[bname] = vals
        flag = "⚠️ " if avg < 0.95 or avg > 1.05 else "   "
        v_str = "  ".join(f"{v:.4f}" for v in vals[:3])
        print(f"{flag} {bname:<30} {v_str}")

    # ── 선로 손실 ──
    # Circuit.Losses() → [W, VAr]  /  TotalPower() → [kW, kvar]
    print("\n⚡ 총 손실")
    losses = dss.Circuit.Losses()   # 단위: W
    print(f"  유효전력 손실 : {losses[0]/1000:.2f} kW  ({losses[0]/1e6:.4f} MW)")
    print(f"  무효전력 손실 : {losses[1]/1000:.2f} kVAr")

    # ── 서브스테이션 공급 전력 ──
    print("\n🏭 변전소 공급 전력")
    src = dss.Circuit.TotalPower()   # 단위: kW, kvar
    print(f"  P = {-src[0]/1000:.3f} MW   Q = {-src[1]/1000:.3f} MVAr")

    # ── 선로별 전류 (과부하 확인) ──
    print("\n🔌 선로 전류 [A] (정격 초과 경고)")
    dss.Lines.First()
    while True:
        name   = dss.Lines.Name()
        i_mag  = dss.CktElement.CurrentsMagAng()   # [mag,ang, mag,ang, ...]
        # 3상이면 6개 (from측 3상), 양방향이면 12개
        currents = [i_mag[i] for i in range(0, min(6, len(i_mag)), 2)]
        i_max  = max(currents) if currents else 0
        flag   = "⚠️ " if i_max > 400 else "   "
        print(f"{flag} {name:<35} {i_max:7.1f} A")
        if not dss.Lines.Next():
            break

    # ── 피더별 요약 ──
    print("\n📊 피더별 PV 역조류 확인")
    for pv_name in ["PV1_좌측1", "PV2_좌우말단", "PV3_우측1", "PV4_우우말단", "F2_PV_지선2"]:
        safe = pv_name.replace(" ", "_")
        if not dss.Circuit.SetActiveElement(f"PVSystem.{safe}"):
            continue
        pwr = dss.CktElement.Powers()   # [kW, kvar per phase, ...]
        p_total = sum(pwr[i] for i in range(0, len(pwr), 2))
        print(f"  {pv_name:<20}: {p_total:.1f} kW (음수=역조류)")

    print("\n" + "="*60)
    print(f"  CSV 결과 저장: {OUT_DIR}/")
    print("="*60)


# ── main ─────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Neo4j에서 네트워크 데이터 조회 중...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        sub, buses, lines, loads, pvs, cbs = fetch_network(driver)
    finally:
        driver.close()
    print(f"  버스 {len(buses)}개, 선로 {len(lines)}개, 부하 {len(loads)}개, PV {len(pvs)}개, CB {len(cbs)}개")

    dss_file = build_dss(sub, lines, loads, pvs, cbs)
    run_and_report(dss_file)
