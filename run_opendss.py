"""
Neo4j CIM → OpenDSS Power Flow 시뮬레이션
두 배전선로(피더1: 이진트리, 피더2: 빗살) 동시 해석
"""
import opendssdirect as dss
from neo4j import GraphDatabase
from pathlib import Path

NEO4J_URI  = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "password"

OUT_DIR = Path(__file__).parent / "dss_output"
OUT_DIR.mkdir(exist_ok=True)

# ── 1. Neo4j에서 데이터 조회 ─────────────────────────────────

def fetch_network():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    with driver.session() as s:
        # 변전소
        sub = s.run("MATCH (n:Substation) RETURN n.name AS name, n.voltage_kv AS kv").single()

        # ConnectivityNode (버스)
        buses = s.run("MATCH (n:ConnectivityNode) RETURN n.name AS name").data()

        # ACLineSegment + 연결된 CN 두 개
        lines = s.run("""
            MATCH (cn1:ConnectivityNode)-[:CONNECTS]->(seg:ACLineSegment)-[:CONNECTS]->(cn2:ConnectivityNode)
            RETURN seg.name      AS name,
                   seg.length_km AS length_km,
                   seg.r_ohm     AS r_ohm,
                   seg.x_ohm     AS x_ohm,
                   seg.conductor_mm2 AS mm2,
                   cn1.name      AS from_bus,
                   cn2.name      AS to_bus
        """).data()

        # 부하
        loads = s.run("""
            MATCH (ec:EnergyConsumer)-[:CONNECTED_AT]->(cn:ConnectivityNode)
            RETURN ec.name AS name, ec.p_mw AS p_mw, ec.q_mvar AS q_mvar, cn.name AS bus
        """).data()

        # PV
        pvs = s.run("""
            MATCH (gu:SolarUnit)-[:CONNECTED_AT]->(cn:ConnectivityNode)
            RETURN gu.name AS name, gu.rated_mw AS rated_mw, cn.name AS bus
        """).data()

        # CB (Breaker) — TERMINAL 관계로 from/to 파악
        cbs = s.run("""
            MATCH (cb:Breaker)-[t:TERMINAL]->(cn:ConnectivityNode)
            WITH cb, t.seq AS seq, cn.name AS cn_name
            ORDER BY cb.name, seq
            WITH cb.name AS name, collect(cn_name) AS cns
            RETURN name, cns[0] AS from_bus, cns[1] AS to_bus
        """).data()

    driver.close()
    return sub, buses, lines, loads, pvs, cbs


# ── 2. DSS 스크립트 생성 ──────────────────────────────────────

def build_dss(sub, buses, lines, loads, pvs, cbs):
    kv     = sub["kv"]       # 22.9
    kv_ll  = kv              # 선간전압

    script_lines = []
    w = script_lines.append

    w(f"! ── 22.9kV 배전망 OpenDSS 모델 ──")
    w(f"Clear")
    w(f"New Circuit.KoreanDist22kV basekv={kv_ll} pu=1.0 angle=0 frequency=60 phases=3")
    w(f"~ bus1=CN_변전소모선")
    w(f"~ Isc3=10000  Isc1=10000  ! 무한 버스 (변전소)")
    w("")

    # 기본 전선 코드 정의 (mm²별)
    w("! ── 전선 코드 ──")
    w("New Linecode.ACSR160 nphases=3 r1=0.192 x1=0.361 r0=0.192 x0=0.361 units=km")
    w("New Linecode.ACSR95  nphases=3 r1=0.320 x1=0.380 r0=0.320 x0=0.380 units=km")
    w("New Linecode.ACSR60  nphases=3 r1=0.507 x1=0.395 r0=0.507 x0=0.395 units=km")
    w("")

    mm2_to_code = {160: "ACSR160", 95: "ACSR95", 60: "ACSR60"}

    # CB → OpenDSS Line (switch)
    w("! ── 차단기 (Switch) ──")
    for cb in cbs:
        safe = cb["name"].replace(" ", "_")
        w(f'New Line.{safe} bus1="{cb["from_bus"]}" bus2="{cb["to_bus"]}" '
          f'switch=true length=0.001 linecode=ACSR160')
    w("")

    # ACLineSegment → OpenDSS Line
    w("! ── 선로 구간 ──")
    for ln in lines:
        safe = ln["name"].replace(" ", "_")
        code = mm2_to_code.get(ln["mm2"], "ACSR95")
        w(f'New Line.{safe} bus1="{ln["from_bus"]}" bus2="{ln["to_bus"]}" '
          f'linecode={code} length={ln["length_km"]} units=km')
    w("")

    # EnergyConsumer → OpenDSS Load
    w("! ── 부하 ──")
    for ld in loads:
        safe = ld["name"].replace(" ", "_")
        kw   = ld["p_mw"] * 1000
        kvar = ld["q_mvar"] * 1000
        w(f'New Load.{safe} bus1="{ld["bus"]}" kv={kv_ll} kw={kw:.1f} kvar={kvar:.1f} '
          f'phases=3 model=1 conn=wye')
    w("")

    # SolarUnit → OpenDSS PVSystem
    w("! ── 태양광 PV (50% 출력) ──")
    for pv in pvs:
        safe  = pv["name"].replace(" ", "_")
        kva   = pv["rated_mw"] * 1000
        kw    = kva * 0.5          # 50% irradiance
        w(f'New PVSystem.{safe} bus1="{pv["bus"]}" kv={kv_ll} kva={kva:.0f} '
          f'pmpp={kw:.0f} irradiance=0.5 phases=3 conn=wye')
    w("")

    # 해석 설정
    w("! ── 해석 설정 ──")
    w("Set Voltagebases=[22.9]")
    w("CalcVoltageBases")
    w("Set algorithm=Newton")
    w("Set maxiter=100")
    w("Set tolerance=0.0001")
    w("")
    w("Solve mode=snapshot")
    w("")
    w("! 결과 저장")
    w(f'Export Voltages "{OUT_DIR}/voltages.csv"')
    w(f'Export Losses   "{OUT_DIR}/losses.csv"')
    w(f'Export Powers   "{OUT_DIR}/powers.csv"')

    script = "\n".join(script_lines)
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
    sub, buses, lines, loads, pvs, cbs = fetch_network()
    print(f"  버스 {len(buses)}개, 선로 {len(lines)}개, 부하 {len(loads)}개, PV {len(pvs)}개, CB {len(cbs)}개")

    dss_file = build_dss(sub, buses, lines, loads, pvs, cbs)
    run_and_report(dss_file)
