"""
Korean 22.9kV Distribution Network - CIM/RDF Model
IEC 61968/61970 CIM16 기반 배전 전력망 모델

네트워크 구성:
  변전소 BusbarSection
    → CB (Circuit Breaker)
    → Section① ~ ⑪ (ACLineSegment)
    → EnergyConsumer (부하), SolarGeneratingUnit (태양광 PV)
    → ConnectivityNode (접속점/분기점)
"""

import uuid
from rdflib import Graph, Namespace, RDF, Literal, URIRef
from rdflib.namespace import XSD

# ── 네임스페이스 ──────────────────────────────────────────
CIM = Namespace("http://iec.ch/TC57/2013/CIM-schema-cim16#")

g = Graph()
g.bind("cim", CIM)

# ── 헬퍼 함수 ────────────────────────────────────────────
def new_uri():
    return URIRef(f"urn:uuid:{uuid.uuid4()}")

def add_obj(rdf_type, name):
    """CIM IdentifiedObject 기본 생성"""
    node = new_uri()
    g.add((node, RDF.type, rdf_type))
    g.add((node, CIM["IdentifiedObject.name"], Literal(name)))
    g.add((node, CIM["IdentifiedObject.mRID"], Literal(str(uuid.uuid4()))))
    return node

def add_terminal(equipment, conn_node, seq=1):
    """Terminal: 설비 ↔ ConnectivityNode 연결"""
    t = new_uri()
    g.add((t, RDF.type, CIM["Terminal"]))
    g.add((t, CIM["IdentifiedObject.mRID"], Literal(str(uuid.uuid4()))))
    g.add((t, CIM["Terminal.ConductingEquipment"], equipment))
    g.add((t, CIM["Terminal.ConnectivityNode"], conn_node))
    g.add((t, CIM["ACDCTerminal.sequenceNumber"],
           Literal(seq, datatype=XSD.integer)))
    return t

# ── 변전소 ───────────────────────────────────────────────
substation = add_obj(CIM["Substation"], "변전소")

# 22.9kV VoltageLevel (설비들의 컨테이너)
vl_22kv = add_obj(CIM["VoltageLevel"], "22.9kV_배전레벨")
g.add((vl_22kv, CIM["VoltageLevel.Substation"], substation))
g.add((vl_22kv, CIM["VoltageLevel.BaseVoltage"],
       Literal(22900.0, datatype=XSD.float)))

# 변전소 22.9kV 모선 (BusbarSection)
cn_sub_bus = add_obj(CIM["ConnectivityNode"], "CN_변전소모선")
g.add((cn_sub_bus, CIM["ConnectivityNode.ConnectivityNodeContainer"], vl_22kv))

busbar = add_obj(CIM["BusbarSection"], "BS_변전소22kV모선")
g.add((busbar, CIM["Equipment.EquipmentContainer"], vl_22kv))
add_terminal(busbar, cn_sub_bus)

# ── CB (Circuit Breaker) ─────────────────────────────────
# CB_출력 쪽 ConnectivityNode = Section① 시작점
cn_cb_out = add_obj(CIM["ConnectivityNode"], "CN_CB출력")
g.add((cn_cb_out, CIM["ConnectivityNode.ConnectivityNodeContainer"], vl_22kv))

cb = add_obj(CIM["Breaker"], "CB_변전소출구")
g.add((cb, CIM["Equipment.EquipmentContainer"], substation))
g.add((cb, CIM["Switch.normalOpen"], Literal(False, datatype=XSD.boolean)))
g.add((cb, CIM["Switch.ratedCurrent"], Literal(600.0, datatype=XSD.float)))
add_terminal(cb, cn_sub_bus,  seq=1)   # 모선 쪽
add_terminal(cb, cn_cb_out,   seq=2)   # 피더 시작 쪽

# ── ConnectivityNode (접속점 / 분기점) ────────────────────
def cn(name):
    node = add_obj(CIM["ConnectivityNode"], name)
    g.add((node, CIM["ConnectivityNode.ConnectivityNodeContainer"], vl_22kv))
    return node

cn_bus1  = cn("CN_접속점1_고압A")
cn_bus2  = cn("CN_접속점2_고압B")
cn_bp1   = cn("CN_BranchPoint1")
cn_busL1 = cn("CN_좌측1_고압C_PV1")
cn_bp2L  = cn("CN_BranchPoint2L")
cn_busLL = cn("CN_좌좌말단")
cn_busLR = cn("CN_좌우말단_PV2")
cn_busR1 = cn("CN_우측1_고압D_PV3")
cn_bp2R  = cn("CN_BranchPoint2R")
cn_busRL = cn("CN_우좌말단")
cn_busRR = cn("CN_우우말단_PV4")

# ── ACLineSegment (배전 선로 구간) ────────────────────────
# ACSR 160mm²: r=0.192 Ω/km, x=0.361 Ω/km  (주간선)
# ACSR  95mm²: r=0.320 Ω/km, x=0.380 Ω/km  (분기선)
MAIN = (0.192, 0.361)   # (r, x) per km
SUB  = (0.320, 0.380)

def add_line(name, from_cn, to_cn, length_km, conductor=MAIN):
    r_km, x_km = conductor
    seg = add_obj(CIM["ACLineSegment"], name)
    g.add((seg, CIM["Equipment.EquipmentContainer"], vl_22kv))
    g.add((seg, CIM["Conductor.length"],
           Literal(length_km, datatype=XSD.float)))
    g.add((seg, CIM["ACLineSegment.r"],
           Literal(round(r_km * length_km, 4), datatype=XSD.float)))
    g.add((seg, CIM["ACLineSegment.x"],
           Literal(round(x_km * length_km, 4), datatype=XSD.float)))
    # 영상 임피던스 (r0=3r, x0=3x 근사)
    g.add((seg, CIM["ACLineSegment.r0"],
           Literal(round(r_km * length_km * 3, 4), datatype=XSD.float)))
    g.add((seg, CIM["ACLineSegment.x0"],
           Literal(round(x_km * length_km * 3, 4), datatype=XSD.float)))
    add_terminal(seg, from_cn, seq=1)
    add_terminal(seg, to_cn,   seq=2)
    return seg

# 주간선 (ACSR 160mm²)
add_line("Section①_CB출구~접속점1",  cn_cb_out, cn_bus1,  length_km=0.5)
add_line("Section②_접속점1~접속점2", cn_bus1,   cn_bus2,  length_km=0.8)
add_line("Section③_접속점2~BP1",     cn_bus2,   cn_bp1,   length_km=1.2)
# 분기선 (ACSR 95mm²)
add_line("Section④_BP1~좌측1",       cn_bp1,    cn_busL1, length_km=1.5, conductor=SUB)
add_line("Section⑤_BP1~우측1",       cn_bp1,    cn_busR1, length_km=1.5, conductor=SUB)
add_line("Section⑥_좌측1~BP2L",      cn_busL1,  cn_bp2L,  length_km=1.0, conductor=SUB)
add_line("Section⑦_BP2L~좌좌말단",   cn_bp2L,   cn_busLL, length_km=0.8, conductor=SUB)
add_line("Section⑧_BP2L~좌우말단",   cn_bp2L,   cn_busLR, length_km=0.8, conductor=SUB)
add_line("Section⑨_우측1~BP2R",      cn_busR1,  cn_bp2R,  length_km=1.0, conductor=SUB)
add_line("Section⑩_BP2R~우좌말단",   cn_bp2R,   cn_busRL, length_km=0.8, conductor=SUB)
add_line("Section⑪_BP2R~우우말단",   cn_bp2R,   cn_busRR, length_km=0.8, conductor=SUB)

# ── EnergyConsumer (부하) ────────────────────────────────
def add_load(name, conn_node, p_mw, pf=0.95):
    q_mvar = p_mw * ((1 - pf**2)**0.5 / pf)
    ec = add_obj(CIM["EnergyConsumer"], name)
    g.add((ec, CIM["Equipment.EquipmentContainer"], vl_22kv))
    g.add((ec, CIM["EnergyConsumer.p"],
           Literal(p_mw * 1e6, datatype=XSD.float)))
    g.add((ec, CIM["EnergyConsumer.q"],
           Literal(round(q_mvar * 1e6, 0), datatype=XSD.float)))
    g.add((ec, CIM["EnergyConsumer.pfixed"],
           Literal(p_mw * 1e6, datatype=XSD.float)))
    add_terminal(ec, conn_node)
    return ec

add_load("고압고객A", cn_bus1,  1.5)
add_load("고압고객B", cn_bus2,  2.0)
add_load("고압고객C", cn_busL1, 1.2)
add_load("부하_좌좌", cn_busLL, 1.8)
add_load("부하_좌우", cn_busLR, 0.9)
add_load("고압고객D", cn_busR1, 1.4)
add_load("부하_우좌", cn_busRL, 2.0)
add_load("부하_우우", cn_busRR, 1.3)

# ── SolarGeneratingUnit (태양광 PV) ──────────────────────
def add_pv(name, conn_node, p_mw):
    gu = add_obj(CIM["SolarGeneratingUnit"], name)
    g.add((gu, CIM["Equipment.EquipmentContainer"], vl_22kv))
    g.add((gu, CIM["GeneratingUnit.nominalP"],
           Literal(p_mw * 1e6, datatype=XSD.float)))
    g.add((gu, CIM["GeneratingUnit.maxOperatingP"],
           Literal(p_mw * 1e6, datatype=XSD.float)))
    g.add((gu, CIM["GeneratingUnit.minOperatingP"],
           Literal(0.0, datatype=XSD.float)))
    add_terminal(gu, conn_node)
    return gu

add_pv("PV1_좌측1",    cn_busL1, 1.0)
add_pv("PV2_좌우말단", cn_busLR, 2.0)
add_pv("PV3_우측1",    cn_busR1, 1.5)
add_pv("PV4_우우말단", cn_busRR, 0.5)

# ── CIM XML/RDF 저장 ─────────────────────────────────────
output_path = "korean_distribution_cim.xml"
g.serialize(destination=output_path, format="pretty-xml")
print(f"[완료] CIM XML 저장: {output_path}")
print(f"       트리플 수: {len(g)}")

# ── 토폴로지 요약 출력 ───────────────────────────────────
print("\n" + "="*60)
print("CIM 모델 토폴로지 요약")
print("="*60)

def get_name(node):
    return str(g.value(node, CIM["IdentifiedObject.name"]) or "?")

print("\n[CB (Circuit Breaker)]")
for s in g.subjects(RDF.type, CIM["Breaker"]):
    name = get_name(s)
    open_st = g.value(s, CIM["Switch.normalOpen"])
    rated   = g.value(s, CIM["Switch.ratedCurrent"])
    terminals = list(g.subjects(CIM["Terminal.ConductingEquipment"], s))
    cns = [get_name(g.value(t, CIM["Terminal.ConnectivityNode"])) for t in terminals]
    print(f"  {name}")
    print(f"    상태: {'개방' if str(open_st)=='True' else '투입'}, 정격전류: {rated}A")
    print(f"    연결: {' ↔ '.join(cns)}")

print("\n[ACLineSegment (배전 선로 구간)]")
for s in sorted(g.subjects(RDF.type, CIM["ACLineSegment"]),
                key=lambda n: str(g.value(n, CIM["IdentifiedObject.name"]))):
    name   = get_name(s)
    length = g.value(s, CIM["Conductor.length"])
    r      = g.value(s, CIM["ACLineSegment.r"])
    x      = g.value(s, CIM["ACLineSegment.x"])
    terminals = list(g.subjects(CIM["Terminal.ConductingEquipment"], s))
    cns = []
    for t in sorted(terminals,
                    key=lambda t2: int(g.value(t2, CIM["ACDCTerminal.sequenceNumber"]))):
        cn_node = g.value(t, CIM["Terminal.ConnectivityNode"])
        cns.append(get_name(cn_node))
    print(f"  {name}")
    print(f"    길이={length}km  r={r}Ω  x={x}Ω")
    print(f"    {' → '.join(cns)}")

print("\n[EnergyConsumer (부하)]")
for s in g.subjects(RDF.type, CIM["EnergyConsumer"]):
    name = get_name(s)
    p    = float(g.value(s, CIM["EnergyConsumer.p"]))
    q    = float(g.value(s, CIM["EnergyConsumer.q"]))
    t    = next(g.subjects(CIM["Terminal.ConductingEquipment"], s))
    cn_node = get_name(g.value(t, CIM["Terminal.ConnectivityNode"]))
    print(f"  {name}: P={p/1e6:.1f}MW  Q={q/1e6:.2f}Mvar  @ {cn_node}")

print("\n[SolarGeneratingUnit (태양광 PV)]")
for s in g.subjects(RDF.type, CIM["SolarGeneratingUnit"]):
    name = get_name(s)
    p    = float(g.value(s, CIM["GeneratingUnit.nominalP"]))
    t    = next(g.subjects(CIM["Terminal.ConductingEquipment"], s))
    cn_node = get_name(g.value(t, CIM["Terminal.ConnectivityNode"]))
    print(f"  {name}: 정격={p/1e6:.1f}MW  @ {cn_node}")

print("\n[ConnectivityNode (접속점 / 분기점) — 연결 설비 목록]")
for s in g.subjects(RDF.type, CIM["ConnectivityNode"]):
    name = get_name(s)
    connected = []
    for t in g.subjects(CIM["Terminal.ConnectivityNode"], s):
        eq = g.value(t, CIM["Terminal.ConductingEquipment"])
        if eq is not None:
            eq_type = str(g.value(eq, RDF.type)).split("#")[-1]
            eq_name = get_name(eq)
            connected.append(f"{eq_name}({eq_type})")
    print(f"  {name}")
    for c in connected:
        print(f"    └ {c}")
