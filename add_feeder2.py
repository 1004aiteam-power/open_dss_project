"""
2번 배전선로 추가 스크립트
형상: 간선(trunk) + 3개 지선(lateral) 빗살(fishbone) 구조
기존 DB에 추가 (clear 없음)
"""
import uuid as _uuid
from neo4j import GraphDatabase

NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "password"

def new_uuid():
    return str(_uuid.uuid4())

# ── 2번 피더 데이터 ─────────────────────────────────────────
CB2 = {
    "name": "CB2_변전소출구2",
    "normalOpen": False,
    "ratedCurrent_A": 400.0,
    "from_cn": "CN_변전소모선",   # 기존 모선 공유
    "to_cn":   "CN2_CB출력",
}

CN2_NODES = [
    {"name": "CN2_CB출력",    "type": "Feeder Start"},
    {"name": "CN2_간선1",     "type": "Trunk Junction"},
    {"name": "CN2_간선2",     "type": "Trunk Junction"},
    {"name": "CN2_간선3",     "type": "Trunk Junction"},
    {"name": "CN2_간선말단",  "type": "Trunk End"},
    {"name": "CN2_지선1말단", "type": "Load Point"},
    {"name": "CN2_지선2말단", "type": "Load+PV Point"},
    {"name": "CN2_지선3말단", "type": "Load Point"},
]

# ACSR 스펙
CONDUCTOR_SPEC = {
    "main": {"mm2": 160, "r_per_km": 0.192, "x_per_km": 0.361},
    "sub":  {"mm2":  95, "r_per_km": 0.320, "x_per_km": 0.380},
    "lat":  {"mm2":  60, "r_per_km": 0.507, "x_per_km": 0.395},
}

SEGMENTS2 = [
    # 간선 (trunk)
    {"name": "F2_SectionA", "label": "CB출구~간선1",
     "from": "CN2_CB출력",  "to": "CN2_간선1",    "length_km": 0.6, "conductor": "main"},
    {"name": "F2_SectionB", "label": "간선1~간선2",
     "from": "CN2_간선1",   "to": "CN2_간선2",    "length_km": 1.0, "conductor": "main"},
    {"name": "F2_SectionC", "label": "간선2~간선3",
     "from": "CN2_간선2",   "to": "CN2_간선3",    "length_km": 1.0, "conductor": "main"},
    {"name": "F2_SectionD", "label": "간선3~간선말단",
     "from": "CN2_간선3",   "to": "CN2_간선말단", "length_km": 0.8, "conductor": "sub"},
    # 지선 (laterals)
    {"name": "F2_SectionL1", "label": "간선1~지선1말단",
     "from": "CN2_간선1",   "to": "CN2_지선1말단", "length_km": 0.5, "conductor": "lat"},
    {"name": "F2_SectionL2", "label": "간선2~지선2말단",
     "from": "CN2_간선2",   "to": "CN2_지선2말단", "length_km": 0.7, "conductor": "lat"},
    {"name": "F2_SectionL3", "label": "간선3~지선3말단",
     "from": "CN2_간선3",   "to": "CN2_지선3말단", "length_km": 0.6, "conductor": "lat"},
]

LOADS2 = [
    {"name": "F2_고객1", "cn": "CN2_지선1말단", "p_mw": 0.8},
    {"name": "F2_고객2", "cn": "CN2_지선2말단", "p_mw": 1.2},
    {"name": "F2_고객3", "cn": "CN2_지선3말단", "p_mw": 1.0},
    {"name": "F2_간선말단고객", "cn": "CN2_간선말단", "p_mw": 0.6},
]

PV2 = [
    {"name": "F2_PV_지선2", "cn": "CN2_지선2말단", "rated_mw": 1.5},
]


def load_feeder2():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as s:
        # CB2 생성
        s.run("""
            MERGE (cb:Breaker {name: $name})
            ON CREATE SET cb.uuid = $uuid
            SET cb.normalOpen     = $normalOpen,
                cb.ratedCurrent_A = $ratedCurrent_A
        """, uuid=new_uuid(), name=CB2["name"],
             normalOpen=CB2["normalOpen"], ratedCurrent_A=CB2["ratedCurrent_A"])

        # CB2 ↔ CN 연결 (기존 CN_변전소모선 재사용)
        s.run("""
            MATCH  (cn1:ConnectivityNode {name: $from_cn})
            MERGE  (cn2:ConnectivityNode {name: $to_cn})
            ON CREATE SET cn2.uuid = $uuid2, cn2.type = 'Feeder Start'
            MERGE  (cb:Breaker {name: $name})
            MERGE  (cb)-[:TERMINAL {seq: 1}]->(cn1)
            MERGE  (cb)-[:TERMINAL {seq: 2}]->(cn2)
        """, from_cn=CB2["from_cn"], to_cn=CB2["to_cn"],
             uuid2=new_uuid(), name=CB2["name"])
        print(f"[CB] {CB2['name']} 생성")

        # ConnectivityNode 생성 (CN2_CB출력은 위에서 이미 MERGE됨)
        for cn in CN2_NODES[1:]:  # CB출력 제외
            s.run("""
                MERGE (n:ConnectivityNode {name: $name})
                ON CREATE SET n.uuid = $uuid
                SET n.type = $type
            """, uuid=new_uuid(), **cn)
        print(f"[CN] {len(CN2_NODES)}개 ConnectivityNode 생성")

        # ACLineSegment 생성 + CONNECTS
        for seg in SEGMENTS2:
            spec = CONDUCTOR_SPEC[seg["conductor"]]
            length = seg["length_km"]
            r = round(spec["r_per_km"] * length, 4)
            x = round(spec["x_per_km"] * length, 4)

            s.run("""
                MERGE (seg:ACLineSegment {name: $name})
                ON CREATE SET seg.uuid = $uuid
                SET seg.label         = $label,
                    seg.length_km     = $length,
                    seg.conductor_mm2 = $mm2,
                    seg.r_ohm         = $r,
                    seg.x_ohm         = $x
            """, uuid=new_uuid(), name=seg["name"], label=seg["label"],
                 length=length, mm2=spec["mm2"], r=r, x=x)

            s.run("""
                MATCH (seg:ACLineSegment    {name: $seg_name})
                MERGE (cn1:ConnectivityNode {name: $from_cn})
                MERGE (cn2:ConnectivityNode {name: $to_cn})
                MERGE (cn1)-[:CONNECTS {direction: 'from'}]->(seg)
                MERGE (seg)-[:CONNECTS {direction: 'to'}  ]->(cn2)
            """, seg_name=seg["name"], from_cn=seg["from"], to_cn=seg["to"])
        print(f"[Section] {len(SEGMENTS2)}개 ACLineSegment 생성")

        # 부하
        pf = 0.95
        for ld in LOADS2:
            q = round(ld["p_mw"] * ((1 - pf**2)**0.5 / pf), 3)
            s.run("""
                MERGE (ec:EnergyConsumer {name: $name})
                ON CREATE SET ec.uuid = $uuid
                SET ec.p_mw = $p, ec.q_mvar = $q, ec.pf = 0.95
                WITH ec
                MATCH (cn:ConnectivityNode {name: $cn})
                MERGE (ec)-[:CONNECTED_AT]->(cn)
            """, uuid=new_uuid(), name=ld["name"], p=ld["p_mw"], q=q, cn=ld["cn"])
        print(f"[부하] {len(LOADS2)}개 EnergyConsumer 생성")

        # PV
        for pv in PV2:
            s.run("""
                MERGE (gu:SolarUnit {name: $name})
                ON CREATE SET gu.uuid = $uuid
                SET gu.rated_mw  = $rated,
                    gu.max_mw    = $rated,
                    gu.min_mw    = 0.0,
                    gu.cim_class = 'SolarGeneratingUnit'
                WITH gu
                MATCH (cn:ConnectivityNode {name: $cn})
                MERGE (gu)-[:CONNECTED_AT]->(cn)
            """, uuid=new_uuid(), name=pv["name"], rated=pv["rated_mw"], cn=pv["cn"])
        print(f"[PV] {len(PV2)}개 SolarUnit 생성")

    driver.close()

    # 결과 확인
    driver2 = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver2.session() as s:
        counts = s.run("""
            MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY label
        """).data()
        rels = s.run("MATCH ()-[r]->() RETURN count(r) AS cnt").single()["cnt"]
    driver2.close()

    print("\n=== DB 현황 ===")
    for row in counts:
        print(f"  ({row['label']}): {row['cnt']}개")
    print(f"  [관계]: {rels}개")


if __name__ == "__main__":
    load_feeder2()
