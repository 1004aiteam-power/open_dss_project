"""
Flask + Neo4j — 전력계통 Viewer + 시뮬레이션 API
"""
from flask import Flask, jsonify, render_template, request
from neo4j import GraphDatabase
from pathlib import Path
import opendssdirect as dss
import tempfile, os, json
from datetime import datetime

from network_model import (
    NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, AMPACITY,
    fetch_network, build_dss_script,
)

app = Flask(__name__)

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

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

def _build_and_solve(pv_irradiance=0.5, mode="snapshot"):
    sub, buses, lines, loads, pvs, cbs = fetch_network(driver)
    script = build_dss_script(sub, lines, loads, pvs, cbs, pv_irradiance=pv_irradiance, mode=mode)

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
    converged, *_ = _build_and_solve(pv_irradiance=0.0, mode="faultstudy")
    if not converged:
        return jsonify({"error": "수렴 실패"}), 500
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
    return jsonify({"converged": converged, "buses": result, "feeders": _get_feeder_loads()})


# ── 그래프 저장 ────────────────────────────────────────────────
#
# 저장은 하나의 트랜잭션으로 처리한다. 중간에 실패하면 전체가 롤백되어
# 관계만 지워진 "반쪽 계통"이 DB에 남지 않는다.
# 저장 직전 상태는 backups/ 에 JSON으로 남긴다 (최근 BACKUP_KEEP개 유지).
# EDIT_TOKEN 환경변수가 설정되면 X-Edit-Token 헤더가 일치해야 저장된다.

VALID_LABELS = {"Substation", "Breaker", "ConnectivityNode", "SolarUnit",
                "ACLineSegment", "EnergyConsumer"}
VALID_REL_TYPES = {"CONNECTS", "TERMINAL", "CONNECTED_AT"}
BACKUP_DIR  = Path(os.environ.get("BACKUP_DIR", Path(__file__).parent / "backups"))
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", 20))
EDIT_TOKEN  = os.environ.get("EDIT_TOKEN")


class SaveValidationError(ValueError):
    pass


def _validate_payload(data):
    """저장 요청 검증. 문제가 있으면 SaveValidationError."""
    if not isinstance(data, dict):
        raise SaveValidationError("요청 본문이 JSON 객체가 아닙니다.")
    nodes, links = data.get("nodes"), data.get("links")
    if not isinstance(nodes, list) or not isinstance(links, list):
        raise SaveValidationError("nodes, links 는 배열이어야 합니다.")
    if not nodes:
        raise SaveValidationError("노드가 하나도 없는 그래프는 저장할 수 없습니다. (전체 삭제 방지)")

    ids = set()
    for n in nodes:
        nid = n.get("id") if isinstance(n, dict) else None
        if not isinstance(nid, str) or not nid:
            raise SaveValidationError("id 가 없는 노드가 있습니다.")
        if nid in ids:
            raise SaveValidationError(f"중복된 노드 id: {nid}")
        ids.add(nid)
    for l in links:
        if not isinstance(l, dict) or l.get("source") not in ids or l.get("target") not in ids:
            raise SaveValidationError("존재하지 않는 노드를 가리키는 연결이 있습니다.")
    return nodes, links


def _scalar_props(d, exclude):
    """Neo4j 에 저장 가능한 값(스칼라/스칼라 리스트)만 남긴다."""
    ok = (str, int, float, bool)
    out = {}
    for k, v in d.items():
        if k in exclude or v is None:
            continue
        if isinstance(v, ok) or (isinstance(v, list) and all(isinstance(x, ok) for x in v)):
            out[k] = v
    return out


def _to_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _backup_graph():
    """현재 DB 그래프를 JSON 파일로 백업하고 오래된 백업은 정리."""
    global _graph_cache
    _graph_cache = None
    snapshot = query_graph()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"graph_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, default=str), encoding="utf-8")
    for old in sorted(BACKUP_DIR.glob("graph_*.json"))[:-BACKUP_KEEP]:
        old.unlink(missing_ok=True)
    return path


def _save_tx(tx, nodes, links):
    """그래프 전체를 동기화 (단일 트랜잭션 안에서 실행)."""
    client_ids = {n["id"] for n in nodes}
    db_ids = {r["id"] for r in tx.run("MATCH (n) RETURN elementId(n) AS id")}

    # 1. 관계 삭제 후 재생성 / 클라이언트에 없는 노드 삭제
    tx.run("MATCH ()-[r]->() DELETE r")
    deleted = list(db_ids - client_ids)
    if deleted:
        tx.run("MATCH (n) WHERE elementId(n) IN $ids DETACH DELETE n", ids=deleted)

    # 2. 노드 갱신/생성
    id_mapping = {}
    for n in nodes:
        nid = n["id"]
        props = _scalar_props(n, {"id", "label", "x", "y"})
        x, y = _to_float(n.get("x")), _to_float(n.get("y"))
        if nid in db_ids:
            tx.run("MATCH (n) WHERE elementId(n) = $id SET n += $props, n.x = $x, n.y = $y",
                   id=nid, props=props, x=x, y=y)
            id_mapping[nid] = nid
        else:
            label = n.get("label") if n.get("label") in VALID_LABELS else "ConnectivityNode"
            rec = tx.run(f"CREATE (n:{label}) SET n = $props, n.x = $x, n.y = $y "
                         "RETURN elementId(n) AS id", props=props, x=x, y=y).single()
            id_mapping[nid] = rec["id"]

    # 3. 관계 재생성
    for l in links:
        rel = l.get("type") if l.get("type") in VALID_REL_TYPES else "CONNECTS"
        props = _scalar_props(l, {"id", "source", "target", "type"})
        rec = tx.run(f"""
            MATCH (a), (b) WHERE elementId(a) = $src AND elementId(b) = $tgt
            CREATE (a)-[r:{rel}]->(b) SET r += $props
            RETURN count(r) AS c
        """, src=id_mapping[l["source"]], tgt=id_mapping[l["target"]], props=props).single()
        if rec["c"] != 1:
            raise SaveValidationError("연결 생성에 실패했습니다. 저장을 취소합니다.")

    return {"nodes": len(nodes), "links": len(links), "deleted_nodes": len(deleted)}


@app.route("/api/graph/save", methods=["POST"])
def save_graph():
    global _graph_cache
    if EDIT_TOKEN and request.headers.get("X-Edit-Token") != EDIT_TOKEN:
        return jsonify({"success": False, "error": "편집 권한이 없습니다. (토큰 불일치)"}), 401

    try:
        nodes, links = _validate_payload(request.get_json(silent=True))
    except SaveValidationError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    backup = _backup_graph()
    try:
        with driver.session() as session:
            summary = session.execute_write(_save_tx, nodes, links)
    except SaveValidationError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    finally:
        _graph_cache = None

    return jsonify({"success": True, "backup": backup.name, **summary})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5100))
    app.run(debug=False, port=port, use_reloader=False, threaded=False)
