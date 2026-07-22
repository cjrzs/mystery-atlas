from .schemas import GraphEdge, GraphNode, ReviewItem, WorkSummary


WORKS = [
    WorkSummary(
        slug="fog-harbor-clocktower",
        title="雾港钟楼",
        author="林砚川",
        region="中国",
        year=2024,
        tags=["本格", "暴风雪山庄", "时间诡计"],
        cases=3,
        people=18,
        clues=42,
        analysis_progress=100,
        status="published",
    )
]

NODES = [
    GraphNode(id="shen-yan", name="沈砚", role="调查记者", group="investigator", first_chapter=1, description="受邀记录钟楼修复工程。"),
    GraphNode(id="liang-bingwen", name="梁秉文", role="钟楼所有人 / 死者", group="victim", first_chapter=1, description="死于封闭的钟楼机芯室。"),
    GraphNode(id="gu-qinghe", name="顾青禾", role="钟表修复师", group="outsider", first_chapter=1, description="最后见到死者的人之一。"),
    GraphNode(id="liang-zhiwei", name="梁知微", role="长女", group="family", first_chapter=2, description="与父亲存在遗产冲突。"),
]

EDGES = [
    GraphEdge(id="e1", source="liang-bingwen", target="liang-zhiwei", label="父女", kind="family", status="confirmed", first_chapter=2, evidence="第 2 章，遗嘱晚宴"),
    GraphEdge(id="e2", source="gu-qinghe", target="liang-bingwen", label="最后见面", kind="testimony", status="disputed", first_chapter=3, evidence="第 3 章口供；第 7 章门锁记录与其冲突"),
    GraphEdge(id="e3", source="shen-yan", target="gu-qinghe", label="共同查钟", kind="action", status="confirmed", first_chapter=4, evidence="第 4 章，两人拆检报时连杆"),
]

REVIEW_ITEMS = [
    ReviewItem(id="review-31", entity_type="relation", title="顾青禾可能提前设置报时连杆", chapter=8, status="needs_review", confidence=0.71, evidence_count=3),
    ReviewItem(id="review-32", entity_type="evidence", title="医生遗漏左腕针孔", chapter=7, status="conflict", confidence=0.56, evidence_count=2),
    ReviewItem(id="review-33", entity_type="identity", title="雨衣人与修复师身份可能重合", chapter=14, status="low_confidence", confidence=0.42, evidence_count=2),
]

