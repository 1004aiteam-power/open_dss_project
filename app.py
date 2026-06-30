"""
Flask + Neo4j — 전력계통 Viewer
"""
from flask import Flask, jsonify, render_template
from neo4j import GraphDatabase

app = Flask(__name__)

NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "password"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def query_graph():
    with driver.session() as s:
        # 모든 노드
        node_rows = s.run("""
            MATCH (n)
            RETURN
                elementId(n)   AS id,
                labels(n)[0]   AS label,
                properties(n)  AS props
        """).data()

        # 모든 관계
        rel_rows = s.run("""
            MATCH (a)-[r]->(b)
            RETURN
                elementId(r)   AS id,
                elementId(a)   AS source,
                elementId(b)   AS target,
                type(r)        AS type,
                properties(r)  AS props
        """).data()

    nodes = []
    for row in node_rows:
        nodes.append({
            "id": row["id"],
            **row["props"],
            "label": row["label"],   # Neo4j label overrides any 'label' property
        })

    links = []
    for row in rel_rows:
        links.append({
            "id":     row["id"],
            "source": row["source"],
            "target": row["target"],
            "type":   row["type"],
            **row["props"],
        })

    return {"nodes": nodes, "links": links}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/graph")
def api_graph():
    return jsonify(query_graph())


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5100))
    app.run(debug=True, port=port)
