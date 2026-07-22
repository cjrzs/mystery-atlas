from fastapi import APIRouter, HTTPException, Query

from ..demo import EDGES, NODES, WORKS
from ..schemas import GraphSnapshot, WorkSummary

router = APIRouter(prefix="/works", tags=["public works"])


@router.get("", response_model=list[WorkSummary])
def list_works() -> list[WorkSummary]:
    return WORKS


@router.get("/{slug}", response_model=WorkSummary)
def get_work(slug: str) -> WorkSummary:
    work = next((item for item in WORKS if item.slug == slug), None)
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    return work


@router.get("/{slug}/graph", response_model=GraphSnapshot)
def get_graph(
    slug: str,
    through_chapter: int = Query(default=1, ge=1, le=999),
) -> GraphSnapshot:
    if not any(item.slug == slug for item in WORKS):
        raise HTTPException(status_code=404, detail="Work not found")

    visible_nodes = [item for item in NODES if item.first_chapter <= through_chapter]
    node_ids = {item.id for item in visible_nodes}
    visible_edges = [
        item
        for item in EDGES
        if item.first_chapter <= through_chapter
        and item.source in node_ids
        and item.target in node_ids
    ]
    return GraphSnapshot(
        work_slug=slug,
        through_chapter=through_chapter,
        nodes=visible_nodes,
        edges=visible_edges,
    )

