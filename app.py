"""
Flask + Neo4j — 전력계통 Viewer + 시뮬레이션 API
"""
from flask import Flask, jsonify, render_template, request
from neo4j import GraphDatabase
from pathlib import Path
import opendssdirect as dss
import tempfile, os

app = Flask(__name__)

NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "password"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

AMPACITY = {160: 400, 95: 310, 60: 240}   # ACSR mm² → 정격전류 A

_graph_cache = None  # 그래프 데이터 메모리 캐시


# ── 그래프 조회 ────────────────────────────────────────────────

def query_graph():
    global _graph_cache
    if _graph_cache is not None:
        return _graph_cache

    with driver.session() as s:
        rows = s.run("""
            MATCH (n)
            OPTIONAL MATCH (n)-[r]->(m)
            WITH collect(DISTINCT {id: elementId(n), label: labels(n)[0], props: properties(n)}) AS ns,
                 collect(DISTINCT CASE WHEN r IS NOT NULL THEN
                   {id: elementId(r), source: elementId(n), target: elementId(m),
                    type: type(r), props: properties(r)} END) AS rs
            RETURN ns, rs
        """).single()
        node_rows = rows["ns"]
        rel_rows  = [r for r in rows["rs"] if r is not None]

    nodes = [{"id": r["id"], **r["props"], "label": r["label"]} for r in node_rows]
    links = [{"id": r["id"], "source": r["source"], "target": r["target"],
              "type": r["type"], **r["props"]} for r in rel_rows]
    _graph_cache = {"nodes": nodes, "links": links}
    return _graph_cache


# ── OpenDSS 공통 헬퍼 ─────────────────────────────────────────

def _fetch_network():
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


def _build_and_solve(pv_irradiance=0.5, mode="snapshot"):
    sub, buses, lines, loads, pvs, cbs = _fetch_network()
    kv = sub["kv"]
    mm2_to_code = {160: "ACSR160", 95: "ACSR95", 60: "ACSR60"}

    sc = []
    w  = sc.append
    w(f"Clear")
    w(f"New Circuit.KorDist basekv={kv} pu=1.0 angle=0 frequency=60 phases=3")
    w(f"~ bus1=CN_변전소모선 Isc3=10000 Isc1=10000")
    w("New Linecode.ACSR160 nphases=3 r1=0.192 x1=0.361 r0=0.192 x0=0.361 units=km")
    w("New Linecode.ACSR95  nphases=3 r1=0.320 x1=0.380 r0=0.320 x0=0.380 units=km")
    w("New Linecode.ACSR60  nphases=3 r1=0.507 x1=0.395 r0=0.507 x0=0.395 units=km")

    for cb in cbs:
        safe = cb["name"].replace(" ", "_")
        w(f'New Line.{safe} bus1="{cb["from_bus"]}" bus2="{cb["to_bus"]}" switch=true length=0.001 linecode=ACSR160')

    for ln in lines:
        safe = ln["name"].replace(" ", "_")
        code = mm2_to_code.get(ln["mm2"], "ACSR95")
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

    script = "\n".join(sc)
    tmp = tempfile.NamedTemporaryFile(suffix=".dss", mode="w", delete=False, encoding="utf-8")
    tmp.write(script)
    tmp.close()

    dss.run_command(f'Redirect "{tmp.name}"')
    os.unlink(tmp.name)

    return dss.Solution.Converged(), lines, pvs, cbs


def _get_feeder_loads():
    feeder_data = {}
    # Feeder 1 (CB_변전소출구)
    if dss.Circuit.SetActiveElement("Line.CB_변전소출구"):
        pwr = dss.CktElement.Powers()
        # 3상 송전단 유효/무효 전력 합산 후 MW/MVar 변환 (유출 방향을 양수로)
        p_mw = -sum(pwr[i] for i in range(0, 6, 2)) / 1000.0
        q_mvar = -sum(pwr[i+1] for i in range(0, 6, 2)) / 1000.0
        feeder_data["Feeder 1"] = {"p_mw": round(p_mw, 3), "q_mvar": round(q_mvar, 3)}
    else:
        feeder_data["Feeder 1"] = {"p_mw": 0.0, "q_mvar": 0.0}

    # Feeder 2 (CB2_변전소출구2)
    if dss.Circuit.SetActiveElement("Line.CB2_변전소출구2"):
        pwr = dss.CktElement.Powers()
        p_mw = -sum(pwr[i] for i in range(0, 6, 2)) / 1000.0
        q_mvar = -sum(pwr[i+1] for i in range(0, 6, 2)) / 1000.0
        feeder_data["Feeder 2"] = {"p_mw": round(p_mw, 3), "q_mvar": round(q_mvar, 3)}
    else:
        feeder_data["Feeder 2"] = {"p_mw": 0.0, "q_mvar": 0.0}

    return feeder_data


# ── Flask 라우트 ───────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/graph")
def api_graph():
    return jsonify(query_graph())


@app.route("/api/graph/refresh")
def api_graph_refresh():
    global _graph_cache
    _graph_cache = None
    return jsonify(query_graph())


@app.route("/api/sim/voltage")
def sim_voltage():
    converged, *_ = _build_and_solve(pv_irradiance=0.5)
    if not converged:
        return jsonify({"error": "수렴 실패"}), 500
    result = {}
    bus_names = dss.Circuit.AllBusNames()
    bus_volts = dss.Circuit.AllBusMagPu()
    idx = 0
    for bname in bus_names:
        dss.Circuit.SetActiveBus(bname)
        n = dss.Bus.NumNodes()
        vals = bus_volts[idx:idx+n]; idx += n
        avg = sum(vals)/len(vals) if vals else 1.0
        result[bname] = {"pu": round(avg,4), "phases": [round(v,4) for v in vals],
                         "status": "over" if avg>1.05 else ("under" if avg<0.95 else "normal")}
    losses = dss.Circuit.Losses(); src = dss.Circuit.TotalPower()
    return jsonify({"converged": True, "buses": result,
        "total_loss_kw": round(losses[0]/1000,2), "total_loss_kvar": round(losses[1]/1000,2),
        "source_mw": round(-src[0]/1000,3), "source_mvar": round(-src[1]/1000,3),
        "feeders": _get_feeder_loads()})


@app.route("/api/sim/thermal")
def sim_thermal():
    converged, lines, *_ = _build_and_solve(pv_irradiance=0.5)
    if not converged:
        return jsonify({"error": "수렴 실패"}), 500
    result = {}
    dss.Lines.First()
    while True:
        name = dss.Lines.Name()
        imag = dss.CktElement.CurrentsMagAng()
        currents = [imag[i] for i in range(0, min(6,len(imag)), 2)]
        i_max = max(currents) if currents else 0.0
        ln_info = next((l for l in lines if l["name"].replace(" ","_").lower()==name.lower()), None)
        rated = AMPACITY.get(ln_info["mm2"] if ln_info else 0, 310)
        pct   = round(i_max/rated*100,1) if rated else 0
        result[name] = {"current_a": round(i_max,1), "rated_a": rated, "loading_pct": pct,
                        "status": "overload" if pct>100 else ("warning" if pct>80 else "normal")}
        if not dss.Lines.Next(): break
    return jsonify({"converged": True, "lines": result, "feeders": _get_feeder_loads()})


@app.route("/api/sim/reverse")
def sim_reverse():
    converged, lines, pvs, cbs = _build_and_solve(pv_irradiance=1.0)
    if not converged:
        return jsonify({"error": "수렴 실패"}), 500
    pv_result = {}
    for pv in pvs:
        safe = pv["name"].replace(" ","_")
        if dss.Circuit.SetActiveElement(f"PVSystem.{safe}"):
            pwr = dss.CktElement.Powers()
            p_total = sum(pwr[i] for i in range(0, len(pwr), 2))
            pv_result[pv["name"]] = {"bus": pv["bus"], "rated_mw": pv["rated_mw"],
                                     "output_kw": round(p_total,1), "reverse": p_total < -10}
    line_result = {}
    dss.Lines.First()
    while True:
        name = dss.Lines.Name()
        pwr  = dss.CktElement.Powers()
        p1   = sum(pwr[i] for i in range(0, min(6,len(pwr)), 2))
        line_result[name] = {"p_kw": round(p1,1), "reverse": p1 < 0}
        if not dss.Lines.Next(): break
    losses = dss.Circuit.Losses(); src = dss.Circuit.TotalPower()
    return jsonify({"converged": True, "pv_irradiance": 1.0,
        "pvs": pv_result, "lines": line_result,
        "source_mw": round(-src[0]/1000,3), "total_loss_kw": round(losses[0]/1000,2),
        "feeders": _get_feeder_loads()})


@app.route("/api/sim/fault")
def sim_fault():
    _build_and_solve(pv_irradiance=0.0, mode="faultstudy")
    dss.run_command("Set mode=faultstudy")
    dss.run_command("Solve")
    result = {}
    for bname in dss.Circuit.AllBusNames():
        dss.Circuit.SetActiveBus(bname)
        try:
            isc  = dss.Bus.Isc()
            mags = [abs(complex(isc[i],isc[i+1])) for i in range(0,len(isc)-1,2)]
            i3ph = max(mags) if mags else 0.0
            result[bname] = {"isc3_a": round(i3ph,1), "isc3_ka": round(i3ph/1000,3),
                             "mva": round(i3ph*22.9*1.732/1000,1),
                             "status": "high" if i3ph>5000 else ("medium" if i3ph>1000 else "low")}
        except Exception:
            result[bname] = {"isc3_a":0, "isc3_ka":0, "mva":0, "status":"low"}
    return jsonify({"converged": True, "buses": result, "feeders": _get_feeder_loads()})


@app.route("/api/graph/save", methods=["POST"])
def save_graph():
    global _graph_cache
    data = request.json
    nodes = data.get("nodes", [])
    links = data.get("links", [])

    with driver.session() as session:
        # 1. 모든 관계 삭제 (새로 빌드)
        session.run("MATCH ()-[r]->() DELETE r")

        # 2. 클라이언트 노드 ID 셋 확보
        client_node_ids = {n["id"] for n in nodes}

        # 3. DB에 존재하나 클라이언트에 없는 노드 검출 후 DETACH DELETE
        db_nodes = session.run("MATCH (n) RETURN elementId(n) AS id").data()
        db_node_ids = {r["id"] for r in db_nodes}
        deleted_ids = db_node_ids - client_node_ids
        
        if deleted_ids:
            session.run("MATCH (n) WHERE elementId(n) IN $ids DETACH DELETE n", ids=list(deleted_ids))

        # 4. 노드 동기화 및 신규 ID 매핑
        id_mapping = {}
        valid_labels = {"Substation", "Breaker", "ConnectivityNode", "SolarUnit", "ACLineSegment", "EnergyConsumer"}

        for n in nodes:
            nid = n.get("id")
            label = n.get("label", "ConnectivityNode")
            
            # Neo4j 저장에 적절한 속성 필터링 (id, label, x, y 제외)
            props = {k: v for k, v in n.items() if k not in ["id", "label", "x", "y"]}
            
            # x, y 좌표는 실수형으로 형변환하여 저장
            try:
                x = float(n.get("x")) if n.get("x") is not None else None
                y = float(n.get("y")) if n.get("y") is not None else None
            except ValueError:
                x, y = None, None

            # DB 존재 여부 판단
            exists = False
            # UUID의 경우 보통 DB elementId로 존재하지 않음 (문자열 형식)
            if nid and not nid.startswith("new_") and len(nid) > 10:
                res_check = session.run("MATCH (n) WHERE elementId(n) = $id RETURN count(n) AS c", id=nid).single()
                if res_check and res_check["c"] > 0:
                    exists = True

            if exists:
                # 기존 노드 업데이트
                session.run("""
                    MATCH (n) WHERE elementId(n) = $id
                    SET n += $props, n.x = $x, n.y = $y
                """, id=nid, props=props, x=x, y=y)
                id_mapping[nid] = nid
            else:
                # 신규 노드 생성
                node_label = label if label in valid_labels else "ConnectivityNode"
                res_create = session.run(f"""
                    CREATE (n:{node_label})
                    SET n = $props, n.x = $x, n.y = $y
                    RETURN elementId(n) AS new_id
                """, props=props, x=x, y=y).single()
                
                new_id = res_create["new_id"]
                id_mapping[nid] = new_id

        # 5. 에지(관계) 재생성
        valid_types = {"CONNECTS", "TERMINAL", "CONNECTED_AT"}
        for l in links:
            source_raw = l.get("source")
            target_raw = l.get("target")
            rel_type = l.get("type", "CONNECTS")
            edge_type = rel_type if rel_type in valid_types else "CONNECTS"

            source_id = id_mapping.get(source_raw, source_raw)
            target_id = id_mapping.get(target_raw, target_raw)

            # properties(r)을 위한 데이터 필터링
            props = {k: v for k, v in l.items() if k not in ["id", "source", "target", "type"]}

            session.run(f"""
                MATCH (a), (b)
                WHERE elementId(a) = $src AND elementId(b) = $tgt
                CREATE (a)-[r:{edge_type}]->(b)
                SET r += $props
            """, src=source_id, tgt=target_id, props=props)

    # 캐시 무효화
    _graph_cache = None
    return jsonify({"success": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5100))
    app.run(debug=False, port=port, use_reloader=False, threaded=False)
