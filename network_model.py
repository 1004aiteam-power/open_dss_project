"""
Neo4j CIM 그래프 조회 + OpenDSS 스크립트 생성 공통 모듈
app.py, run_opendss.py, cim_neo4j_loader.py, add_feeder2.py 에서 공유

Neo4j 접속 정보는 환경변수로 설정한다 (미설정 시 로컬 기본값 사용):
  NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
"""
import os

NEO4J_URI      = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER     = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")

AMPACITY = {160: 400, 95: 310, 60: 240}          # ACSR mm² → 정격전류 A
MM2_TO_LINECODE = {160: "ACSR160", 95: "ACSR95", 60: "ACSR60"}

LINECODES = [
    "New Linecode.ACSR160 nphases=3 r1=0.192 x1=0.361 r0=0.192 x0=0.361 units=km",
    "New Linecode.ACSR95  nphases=3 r1=0.320 x1=0.380 r0=0.320 x0=0.380 units=km",
    "New Linecode.ACSR60  nphases=3 r1=0.507 x1=0.395 r0=0.507 x0=0.395 units=km",
]


def fetch_network(driver):
    """Neo4j에서 변전소/버스/선로/부하/PV/차단기 데이터 조회"""
    with driver.session() as s:
        sub   = s.run("MATCH (n:Substation) RETURN n.name AS name, n.voltage_kv AS kv").single()
        buses = s.run("MATCH (n:ConnectivityNode) RETURN n.name AS name").data()
        lines = s.run("""
            MATCH (cn1:ConnectivityNode)-[:CONNECTS]->(seg:ACLineSegment)-[:CONNECTS]->(cn2:ConnectivityNode)
            RETURN seg.name AS name, seg.length_km AS length_km,
                   seg.r_ohm AS r_ohm, seg.x_ohm AS x_ohm,
                   seg.conductor_mm2 AS mm2, cn1.name AS from_bus, cn2.name AS to_bus
        """).data()
        loads = s.run("""
            MATCH (ec:EnergyConsumer)-[:CONNECTED_AT]->(cn:ConnectivityNode)
            RETURN ec.name AS name, ec.p_mw AS p_mw, ec.q_mvar AS q_mvar, cn.name AS bus
        """).data()
        pvs = s.run("""
            MATCH (gu:SolarUnit)-[:CONNECTED_AT]->(cn:ConnectivityNode)
            RETURN gu.name AS name, gu.rated_mw AS rated_mw, cn.name AS bus
        """).data()
        cbs = s.run("""
            MATCH (cb:Breaker)-[t:TERMINAL]->(cn:ConnectivityNode)
            WITH cb, t.seq AS seq, cn.name AS cn_name
            ORDER BY cb.name, seq
            WITH cb.name AS name, collect(cn_name) AS cns
            RETURN name, cns[0] AS from_bus, cns[1] AS to_bus
        """).data()
    return sub, buses, lines, loads, pvs, cbs


def build_dss_script(sub, lines, loads, pvs, cbs, pv_irradiance=0.5, mode="snapshot", export_dir=None):
    """네트워크 데이터 → OpenDSS 스크립트 텍스트 생성

    export_dir 이 주어지면 조류계산 결과(Voltages/Losses/Powers)를 CSV로 내보내는
    Export 명령을 스크립트 끝에 추가한다 (run_opendss.py CLI 용도).
    """
    kv = sub["kv"]
    sc = []
    w = sc.append
    w("Clear")
    w(f"New Circuit.KorDist basekv={kv} pu=1.0 angle=0 frequency=60 phases=3")
    w("~ bus1=CN_변전소모선 Isc3=10000 Isc1=10000")
    sc.extend(LINECODES)

    for cb in cbs:
        safe = cb["name"].replace(" ", "_")
        w(f'New Line.{safe} bus1="{cb["from_bus"]}" bus2="{cb["to_bus"]}" switch=true length=0.001 linecode=ACSR160')

    for ln in lines:
        safe = ln["name"].replace(" ", "_")
        code = MM2_TO_LINECODE.get(ln["mm2"], "ACSR95")
        w(f'New Line.{safe} bus1="{ln["from_bus"]}" bus2="{ln["to_bus"]}" linecode={code} length={ln["length_km"]} units=km')

    for ld in loads:
        safe = ld["name"].replace(" ", "_")
        w(f'New Load.{safe} bus1="{ld["bus"]}" kv={kv} kw={ld["p_mw"]*1000:.1f} kvar={ld["q_mvar"]*1000:.1f} phases=3 model=1 conn=wye')

    for pv in pvs:
        safe = pv["name"].replace(" ", "_")
        kva  = pv["rated_mw"] * 1000
        w(f'New PVSystem.{safe} bus1="{pv["bus"]}" kv={kv} kva={kva:.0f} pmpp={kva*pv_irradiance:.0f} irradiance={pv_irradiance} phases=3 conn=wye')

    w("Set Voltagebases=[22.9]")
    w("CalcVoltageBases")
    w("Set algorithm=Newton")
    w("Set maxiter=100")
    w("Set tolerance=0.0001")
    w(f"Solve mode={mode}")

    if export_dir is not None:
        w(f'Export Voltages "{export_dir}/voltages.csv"')
        w(f'Export Losses   "{export_dir}/losses.csv"')
        w(f'Export Powers   "{export_dir}/powers.csv"')

    return "\n".join(sc)
