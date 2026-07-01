"""
Korean 22.9kV Distribution Network — Neo4j CIM Loader
CIM 기반 배전 전력망을 Neo4j 그래프 DB에 로드

Neo4j 접속 정보는 network_model.py 참고 (NEO4J_URI/USER/PASSWORD 환경변수로 설정 가능).
"""

import uuid as _uuid

from neo4j import GraphDatabase

from network_model import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD


def new_uuid():
    return str(_uuid.uuid4())

# ── 네트워크 데이터 정의 ──────────────────────────────────
SUBSTATION = {"name": "변전소", "voltage_kv": 22.9, "source_kv": 154.0}

CIRCUIT_BREAKERS = [
    {
        "name": "CB_변전소출구",
        "normalOpen": False,
        "ratedCurrent_A": 600.0,
        "from_cn": "CN_변전소모선",
        "to_cn": "CN_CB출력",
    },
    {
        "name": "CB2_변전소출구2",
        "normalOpen": False,
        "ratedCurrent_A": 400.0,
        "from_cn": "CN_변전소모선",
        "to_cn": "CN_F2_CB출력",
    },
]

# ConnectivityNode 목록 (접속점 / 분기점)
CONNECTIVITY_NODES = [
    # Feeder 1 (이진트리)
    {"name": "CN_변전소모선",      "type": "Busbar"},
    {"name": "CN_CB출력",          "type": "Feeder Start"},
    {"name": "CN_접속점1_고압A",   "type": "Load Point"},
    {"name": "CN_접속점2_고압B",   "type": "Load Point"},
    {"name": "CN_BranchPoint1",    "type": "Branch Point"},
    {"name": "CN_좌측1_고압C_PV1", "type": "Load+PV Point"},
    {"name": "CN_BranchPoint2L",   "type": "Branch Point"},
    {"name": "CN_좌좌말단",        "type": "Load Point"},
    {"name": "CN_좌우말단_PV2",    "type": "Load+PV Point"},
    {"name": "CN_우측1_고압D_PV3", "type": "Load+PV Point"},
    {"name": "CN_BranchPoint2R",   "type": "Branch Point"},
    {"name": "CN_우좌말단",        "type": "Load Point"},
    {"name": "CN_우우말단_PV4",    "type": "Load+PV Point"},
    # Feeder 2 (빗살)
    {"name": "CN_F2_CB출력",       "type": "Feeder Start"},
    {"name": "CN_F2_분기A",        "type": "Branch Point"},
    {"name": "CN_F2_고객1",        "type": "Load Point"},
    {"name": "CN_F2_분기B",        "type": "Branch Point"},
    {"name": "CN_F2_지선2_PV",     "type": "Load+PV Point"},
    {"name": "CN_F2_분기C",        "type": "Branch Point"},
    {"name": "CN_F2_고객3",        "type": "Load Point"},
    {"name": "CN_F2_말단",         "type": "Load Point"},
]

# ACLineSegment (Section①~⑪)
#   conductor: "main" = ACSR 160mm²  /  "sub" = ACSR 95mm²
LINE_SEGMENTS = [
    # Feeder 1 (이진트리)  — load_p_mw: 말단 접속 부하
    {"name": "Section①", "label": "CB출구~접속점1",
     "from": "CN_CB출력",          "to": "CN_접속점1_고압A",
     "length_km": 0.5,  "conductor": "main", "load_p_mw": 1.5, "load_name": "고압고객A"},
    {"name": "Section②", "label": "접속점1~접속점2",
     "from": "CN_접속점1_고압A",   "to": "CN_접속점2_고압B",
     "length_km": 0.8,  "conductor": "main", "load_p_mw": 2.0, "load_name": "고압고객B"},
    {"name": "Section③", "label": "접속점2~BranchPoint1",
     "from": "CN_접속점2_고압B",   "to": "CN_BranchPoint1",
     "length_km": 1.2,  "conductor": "main"},
    {"name": "Section④", "label": "BranchPoint1~좌측1",
     "from": "CN_BranchPoint1",    "to": "CN_좌측1_고압C_PV1",
     "length_km": 1.5,  "conductor": "sub",  "load_p_mw": 1.2, "load_name": "고압고객C"},
    {"name": "Section⑤", "label": "BranchPoint1~우측1",
     "from": "CN_BranchPoint1",    "to": "CN_우측1_고압D_PV3",
     "length_km": 1.5,  "conductor": "sub",  "load_p_mw": 1.4, "load_name": "고압고객D"},
    {"name": "Section⑥", "label": "좌측1~BranchPoint2L",
     "from": "CN_좌측1_고압C_PV1", "to": "CN_BranchPoint2L",
     "length_km": 1.0,  "conductor": "sub"},
    {"name": "Section⑦", "label": "BranchPoint2L~좌좌말단",
     "from": "CN_BranchPoint2L",   "to": "CN_좌좌말단",
     "length_km": 0.8,  "conductor": "sub",  "load_p_mw": 1.8, "load_name": "부하_좌좌"},
    {"name": "Section⑧", "label": "BranchPoint2L~좌우말단",
     "from": "CN_BranchPoint2L",   "to": "CN_좌우말단_PV2",
     "length_km": 0.8,  "conductor": "sub",  "load_p_mw": 0.9, "load_name": "부하_좌우"},
    {"name": "Section⑨", "label": "우측1~BranchPoint2R",
     "from": "CN_우측1_고압D_PV3", "to": "CN_BranchPoint2R",
     "length_km": 1.0,  "conductor": "sub"},
    {"name": "Section⑩", "label": "BranchPoint2R~우좌말단",
     "from": "CN_BranchPoint2R",   "to": "CN_우좌말단",
     "length_km": 0.8,  "conductor": "sub",  "load_p_mw": 2.0, "load_name": "부하_우좌"},
    {"name": "Section⑪", "label": "BranchPoint2R~우우말단",
     "from": "CN_BranchPoint2R",   "to": "CN_우우말단_PV4",
     "length_km": 0.8,  "conductor": "sub",  "load_p_mw": 1.3, "load_name": "부하_우우"},
    # Feeder 2 (빗살) — 간선
    {"name": "F2_SectionA", "label": "F2_CB출구~분기A",
     "from": "CN_F2_CB출력",  "to": "CN_F2_분기A",
     "length_km": 0.5,  "conductor": "sub"},
    {"name": "F2_SectionB", "label": "F2_분기A~분기B",
     "from": "CN_F2_분기A",   "to": "CN_F2_분기B",
     "length_km": 0.8,  "conductor": "sub"},
    {"name": "F2_SectionC", "label": "F2_분기B~분기C",
     "from": "CN_F2_분기B",   "to": "CN_F2_분기C",
     "length_km": 0.8,  "conductor": "sub"},
    {"name": "F2_SectionD", "label": "F2_분기C~말단",
     "from": "CN_F2_분기C",   "to": "CN_F2_말단",
     "length_km": 0.5,  "conductor": "lat",  "load_p_mw": 0.6, "load_name": "F2_간선말단고객"},
    # Feeder 2 — 지선 (lateral)
    {"name": "F2_SectionL1", "label": "F2_분기A~고객1",
     "from": "CN_F2_분기A",    "to": "CN_F2_고객1",
     "length_km": 0.3,  "conductor": "lat",  "load_p_mw": 0.8, "load_name": "F2_고객1"},
    {"name": "F2_SectionL2", "label": "F2_분기B~지선2",
     "from": "CN_F2_분기B",    "to": "CN_F2_지선2_PV",
     "length_km": 0.3,  "conductor": "lat",  "load_p_mw": 1.2, "load_name": "F2_고객2"},
    {"name": "F2_SectionL3", "label": "F2_분기C~고객3",
     "from": "CN_F2_분기C",    "to": "CN_F2_고객3",
     "length_km": 0.3,  "conductor": "lat",  "load_p_mw": 1.0, "load_name": "F2_고객3"},
]

# ACSR 전선 스펙
CONDUCTOR_SPEC = {
    "main": {"mm2": 160, "r_per_km": 0.192, "x_per_km": 0.361},
    "sub":  {"mm2":  95, "r_per_km": 0.320, "x_per_km": 0.380},
    "lat":  {"mm2":  60, "r_per_km": 0.507, "x_per_km": 0.395},
}

# 태양광 PV (SolarGeneratingUnit)
PV_UNITS = [
    {"name": "PV1_좌측1",    "cn": "CN_좌측1_고압C_PV1", "rated_mw": 1.0},
    {"name": "PV2_좌우말단", "cn": "CN_좌우말단_PV2",    "rated_mw": 2.0},
    {"name": "PV3_우측1",    "cn": "CN_우측1_고압D_PV3", "rated_mw": 1.5},
    {"name": "PV4_우우말단", "cn": "CN_우우말단_PV4",    "rated_mw": 0.5},
    # Feeder 2 PV
    {"name": "F2_PV_지선2", "cn": "CN_F2_지선2_PV",  "rated_mw": 0.75},
]


# ── Neo4j 로더 ────────────────────────────────────────────
class CIMLoader:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def clear_db(self):
        with self.driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")
        print("[초기화] 기존 데이터 삭제 완료")

    def create_constraints(self):
        queries = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:ConnectivityNode) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:ACLineSegment)    REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:EnergyConsumer)   REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:SolarUnit)        REQUIRE n.name IS UNIQUE",
        ]
        with self.driver.session() as s:
            for q in queries:
                s.run(q)
        print("[제약] Unique constraint 생성 완료")

    def load_substation(self):
        with self.driver.session() as s:
            s.run("""
                MERGE (sub:Substation {name: $name})
                ON CREATE SET sub.uuid = $uuid
                SET sub.voltage_kv = $voltage_kv,
                    sub.source_kv  = $source_kv
            """, uuid=new_uuid(), **SUBSTATION)
        print(f"[변전소] {SUBSTATION['name']} 생성")

    def load_circuit_breaker(self):
        with self.driver.session() as s:
            for cb in CIRCUIT_BREAKERS:
                s.run("""
                    MERGE (cb:Breaker {name: $name})
                    ON CREATE SET cb.uuid = $uuid
                    SET cb.normalOpen     = $normalOpen,
                        cb.ratedCurrent_A = $ratedCurrent_A
                """, uuid=new_uuid(), name=cb["name"], normalOpen=cb["normalOpen"],
                     ratedCurrent_A=cb["ratedCurrent_A"])
                s.run("""
                    MERGE (cn1:ConnectivityNode {name: $from_cn})
                    MERGE (cn2:ConnectivityNode {name: $to_cn})
                    MERGE (cb:Breaker {name: $name})
                    MERGE (cb)-[:TERMINAL {seq: 1}]->(cn1)
                    MERGE (cb)-[:TERMINAL {seq: 2}]->(cn2)
                """, from_cn=cb["from_cn"], to_cn=cb["to_cn"], name=cb["name"])
                print(f"[CB] {cb['name']} 생성 및 연결")

    def load_connectivity_nodes(self):
        with self.driver.session() as s:
            for cn in CONNECTIVITY_NODES:
                s.run("""
                    MERGE (n:ConnectivityNode {name: $name})
                    ON CREATE SET n.uuid = $uuid
                    SET n.type = $type
                """, uuid=new_uuid(), **cn)
        print(f"[ConnectivityNode] {len(CONNECTIVITY_NODES)}개 생성")

    def load_line_segments(self):
        with self.driver.session() as s:
            for seg in LINE_SEGMENTS:
                spec = CONDUCTOR_SPEC[seg["conductor"]]
                length = seg["length_km"]
                r = round(spec["r_per_km"] * length, 4)
                x = round(spec["x_per_km"] * length, 4)

                # ACLineSegment 노드
                load_p   = seg.get("load_p_mw")
                load_name= seg.get("load_name")
                pf = 0.95
                load_q   = round(load_p * ((1 - pf**2)**0.5 / pf), 3) if load_p else None
                s.run("""
                    MERGE (seg:ACLineSegment {name: $name})
                    ON CREATE SET seg.uuid = $uuid
                    SET seg.label        = $label,
                        seg.length_km    = $length,
                        seg.conductor_mm2= $mm2,
                        seg.r_ohm        = $r,
                        seg.x_ohm        = $x,
                        seg.load_p_mw    = $load_p,
                        seg.load_q_mvar  = $load_q,
                        seg.load_name    = $load_name
                """, uuid=new_uuid(), name=seg["name"], label=seg["label"],
                     length=length, mm2=spec["mm2"], r=r, x=x,
                     load_p=load_p, load_q=load_q, load_name=load_name)


                # CN → ACLineSegment → CN 위상 경로 (CONNECTS)
                s.run("""
                    MATCH  (seg:ACLineSegment    {name: $seg_name})
                    MERGE  (cn1:ConnectivityNode {name: $from_cn})
                    MERGE  (cn2:ConnectivityNode {name: $to_cn})
                    MERGE  (cn1)-[:CONNECTS {direction: 'from'}]->(seg)
                    MERGE  (seg)-[:CONNECTS {direction: 'to'}  ]->(cn2)
                """, seg_name=seg["name"],
                     from_cn=seg["from"], to_cn=seg["to"])

        print(f"[ACLineSegment] {len(LINE_SEGMENTS)}개 Section 생성 및 연결")

    def load_pv_units(self):
        with self.driver.session() as s:
            for pv in PV_UNITS:
                s.run("""
                    MERGE (gu:SolarUnit {name: $name})
                    ON CREATE SET gu.uuid = $uuid
                    SET gu.rated_mw    = $rated,
                        gu.max_mw      = $rated,
                        gu.min_mw      = 0.0,
                        gu.cim_class   = 'SolarGeneratingUnit'
                    WITH gu
                    MATCH (cn:ConnectivityNode {name: $cn})
                    MERGE (gu)-[:CONNECTED_AT]->(cn)
                """, uuid=new_uuid(), name=pv["name"], rated=pv["rated_mw"], cn=pv["cn"])
        print(f"[SolarUnit] {len(PV_UNITS)}개 PV 생성")

    def print_summary(self):
        with self.driver.session() as s:
            counts = s.run("""
                MATCH (n)
                RETURN labels(n)[0] AS label, count(n) AS cnt
                ORDER BY label
            """).data()
            rels = s.run("MATCH ()-[r]->() RETURN count(r) AS cnt").single()["cnt"]

        print("\n" + "="*50)
        print("Neo4j 로드 완료 — 노드/관계 수")
        print("="*50)
        for row in counts:
            print(f"  ({row['label']}): {row['cnt']}개")
        print(f"  [관계]: {rels}개")
        print("="*50)

    def print_sample_queries(self):
        print("""
Neo4j Browser에서 실행해 볼 쿼리 예시
──────────────────────────────────────
# 전체 그래프 시각화
MATCH (n)-[r]->(m) RETURN n, r, m

# CB에서 말단까지 경로 (Section①→⑧)
MATCH path = (start:ConnectivityNode {name:'CN_CB출력'})
             -[:LINE_SECTION*]->(end:ConnectivityNode)
RETURN path

# 역조류 가능 구간: PV 정격 > 부하
MATCH (pv:SolarUnit)-[:CONNECTED_AT]->(cn:ConnectivityNode)
      <-[:CONNECTED_AT]-(ld:EnergyConsumer)
WHERE pv.rated_mw > ld.p_mw
RETURN cn.name AS 접속점,
       pv.name AS PV, pv.rated_mw AS PV_MW,
       ld.name AS 부하, ld.p_mw AS 부하_MW,
       pv.rated_mw - ld.p_mw AS 잉여_MW

# Branch Point 확인
MATCH (bp:ConnectivityNode {type:'Branch Point'})
MATCH (bp)<-[:LINE_SECTION]-(upstream)
MATCH (bp)-[:LINE_SECTION]->(downstream)
RETURN bp.name, upstream.name, collect(downstream.name)
""")


def main():
    print("Neo4j CIM 모델 로더 시작...")
    loader = CIMLoader(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    try:
        loader.clear_db()
        loader.create_constraints()
        loader.load_substation()
        loader.load_connectivity_nodes()
        loader.load_circuit_breaker()
        loader.load_line_segments()
        loader.load_pv_units()
        loader.print_summary()
        loader.print_sample_queries()
    finally:
        loader.close()


if __name__ == "__main__":
    main()
