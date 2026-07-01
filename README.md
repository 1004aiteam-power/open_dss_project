# 한국형 22.9kV 배전망 CIM/OpenDSS 시뮬레이션

IEC 61968/61970 CIM16 모델 기반의 한국 22.9kV 배전망을 [Neo4j](https://neo4j.com/) 그래프 DB에 적재하고, [OpenDSS](https://www.epri.com/pages/sa/opendss)로 전력조류를 계산하는 프로젝트입니다. Flask 기반 웹 뷰어에서 배전망 토폴로지를 편집하고, 전압/열용량/역조류/고장전류 시뮬레이션 결과를 확인할 수 있습니다.

## 아키텍처

```
cim_model.py           CIM/RDF 모델 정의 → korean_distribution_cim.xml
        │
        ▼
cim_neo4j_loader.py     Neo4j에 피더1(이진트리) 적재
add_feeder2.py          Neo4j에 피더2(빗살) 추가 적재
        │
        ▼
network_model.py        Neo4j 조회 + OpenDSS 스크립트 생성 (공통 모듈)
        │
    ┌───┴────┐
    ▼        ▼
app.py    run_opendss.py
(Flask     (CLI로 조류계산
 웹 서버)   실행 후 CSV 출력)
    │
    ▼
templates/index.html    Cytoscape.js 기반 그래프 뷰어/에디터
```

- **네트워크 구성**: 154kV→22.9kV 변전소, 차단기(CB) 2개(피더1: 이진트리 구조, 피더2: 빗살 구조), ACSR 160/95/60mm² 선로, 부하 및 태양광(PV) 설비
- `pv_analysis.py`, `segment8_pv_comparison.py`는 Neo4j 없이 독립적으로 동작하는 PV 연계 분석/시각화 스크립트입니다.

## 설치

Python 3.10 이상과 실행 중인 Neo4j 인스턴스(Bolt 프로토콜, 기본 `localhost:7687`)가 필요합니다.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Neo4j 접속 정보는 환경변수로 설정할 수 있습니다 (미설정 시 로컬 기본값 사용):

```bash
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="password"
```

## 사용 방법

### 1. Neo4j에 네트워크 데이터 적재

```bash
python3 cim_neo4j_loader.py   # 피더1(이진트리) — 기존 DB 초기화 후 적재
python3 add_feeder2.py        # 피더2(빗살) — 기존 DB에 추가 적재
```

### 2. 웹 뷰어 실행

```bash
python3 app.py    # http://localhost:5100 (PORT 환경변수로 변경 가능)
```

배전망 그래프 조회/편집과 함께 아래 시뮬레이션을 웹에서 바로 실행할 수 있습니다.

| API | 설명 |
|---|---|
| `GET /api/graph` | 그래프 데이터 조회 (캐시됨) |
| `GET /api/graph/refresh` | 그래프 캐시 무효화 후 재조회 |
| `POST /api/graph/save` | 편집한 그래프를 Neo4j에 저장 |
| `GET /api/sim/voltage` | 모선 전압 조류계산 (PV 50% 출력) |
| `GET /api/sim/thermal` | 선로 전류/열용량 부하율 계산 |
| `GET /api/sim/reverse` | PV 전체 출력 시 역조류 확인 |
| `GET /api/sim/fault` | 3상 고장전류(Isc) 계산 |

### 3. CLI로 조류계산만 실행

```bash
python3 run_opendss.py
```

콘솔에 모선 전압/손실/선로 전류 리포트를 출력하고, `dss_output/`에 전압·손실·전력 CSV를 저장합니다.

### 4. PV 연계 분석 스크립트 (독립 실행, Neo4j 불필요)

```bash
python3 pv_analysis.py             # PV 유무에 따른 전체 피더 비교 → pv_analysis_result.png
python3 segment8_pv_comparison.py  # 특정 구간(Section8) PV 연계 비교 → segment8_comparison.png
```

## 파일 구조

| 파일 | 역할 |
|---|---|
| `cim_model.py` | CIM/RDF 배전망 모델 정의, `korean_distribution_cim.xml` 생성 |
| `cim_neo4j_loader.py` | CIM 모델을 Neo4j에 적재 (피더1) |
| `add_feeder2.py` | 피더2(빗살 구조) 추가 적재 |
| `network_model.py` | Neo4j 조회 + OpenDSS 스크립트 생성 공통 모듈 |
| `app.py` | Flask 웹 서버 (그래프 뷰어 + 시뮬레이션 API) |
| `run_opendss.py` | CLI 조류계산 실행 및 리포트 출력 |
| `plot_utils.py` | matplotlib 한글 폰트 설정 유틸 |
| `pv_analysis.py` | 전체 피더 PV 연계 전후 비교 분석 |
| `segment8_pv_comparison.py` | 특정 구간 PV 연계 전후 비교 분석 |
| `templates/index.html` | Cytoscape.js 기반 그래프 뷰어/에디터 UI |
| `dss_output/` | `run_opendss.py` 실행 결과 CSV (전압/손실/전력) |
