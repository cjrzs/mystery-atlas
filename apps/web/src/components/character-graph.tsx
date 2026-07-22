"use client";

import cytoscape, { Core } from "cytoscape";
import { useEffect, useMemo, useRef } from "react";
import type { CharacterNode, RelationEdge } from "@/lib/demo-data";

type GraphSelection =
  | { type: "node"; id: string }
  | { type: "edge"; id: string };

type CharacterGraphProps = {
  nodes: CharacterNode[];
  edges: RelationEdge[];
  chapter: number;
  visibleKinds: Set<RelationEdge["kind"]>;
  selectedId: string;
  onSelect: (selection: GraphSelection) => void;
};

export function CharacterGraph({ nodes, edges, chapter, visibleKinds, selectedId, onSelect }: CharacterGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Core | null>(null);

  const elements = useMemo(() => {
    const visibleNodes = nodes.filter((node) => node.firstChapter <= chapter);
    const nodeIds = new Set(visibleNodes.map((node) => node.id));
    const visibleEdges = edges.filter((edge) => (
      edge.firstChapter <= chapter
      && nodeIds.has(edge.source)
      && nodeIds.has(edge.target)
      && visibleKinds.has(edge.kind)
    ));

    return [
      ...visibleNodes.map((node) => ({
        data: { id: node.id, label: node.name, role: node.role, group: node.group },
        position: { x: node.x, y: node.y },
        classes: `group-${node.group}`,
      })),
      ...visibleEdges.map((edge) => ({
        data: { id: edge.id, source: edge.source, target: edge.target, label: edge.label, status: edge.status },
        classes: `kind-${edge.kind} status-${edge.status}`,
      })),
    ];
  }, [chapter, edges, nodes, visibleKinds]);

  useEffect(() => {
    if (!containerRef.current) return;

    const graph = cytoscape({
      container: containerRef.current,
      elements,
      layout: { name: "preset", fit: true, padding: 50 },
      minZoom: 0.55,
      maxZoom: 1.8,
      wheelSensitivity: 0.18,
      boxSelectionEnabled: false,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "#ffffff",
            "border-color": "#64748b",
            "border-width": 2,
            width: 60,
            height: 60,
            label: "data(label)",
            color: "#17212b",
            "font-family": "Inter, Noto Sans SC, sans-serif",
            "font-size": 12,
            "font-weight": 650,
            "text-valign": "bottom",
            "text-margin-y": 8,
            "text-background-color": "#f5f7f8",
            "text-background-opacity": 0.92,
            "text-background-padding": "3px",
            "text-background-shape": "roundrectangle",
            "overlay-opacity": 0,
          },
        },
        { selector: ".group-investigator", style: { "background-color": "#d9f1ec", "border-color": "#087e6d" } },
        { selector: ".group-victim", style: { "background-color": "#f2e6e3", "border-color": "#9b4a3c" } },
        { selector: ".group-family", style: { "background-color": "#e9edf8", "border-color": "#5369a5" } },
        { selector: ".group-staff", style: { "background-color": "#f7efd8", "border-color": "#9d791e" } },
        { selector: ".group-outsider", style: { "background-color": "#ece9f3", "border-color": "#6f6288" } },
        {
          selector: "edge",
          style: {
            width: 1.7,
            "line-color": "#87919b",
            "target-arrow-color": "#87919b",
            "target-arrow-shape": "none",
            "curve-style": "bezier",
            label: "data(label)",
            color: "#4e5964",
            "font-family": "Inter, Noto Sans SC, sans-serif",
            "font-size": 9,
            "text-background-color": "#f5f7f8",
            "text-background-opacity": 0.94,
            "text-background-padding": "2px",
            "text-rotation": "autorotate",
            "overlay-opacity": 0,
          },
        },
        { selector: ".kind-family", style: { "line-color": "#6274aa" } },
        { selector: ".kind-conflict", style: { "line-color": "#b45042", width: 2.3 } },
        { selector: ".kind-action", style: { "line-color": "#188675" } },
        { selector: ".kind-testimony", style: { "line-color": "#8a6f28" } },
        { selector: ".kind-suspicion", style: { "line-color": "#8a5d9b" } },
        { selector: ".status-inferred", style: { "line-style": "dashed" } },
        { selector: ".status-disputed", style: { "line-style": "dotted", width: 2.6 } },
        { selector: ".is-selected", style: { "border-width": 4, "border-color": "#111827", "z-index": 10 } },
        { selector: "edge.is-selected", style: { width: 4, "line-color": "#111827", "z-index": 10 } },
        { selector: ".is-muted", style: { opacity: 0.17 } },
      ],
    });

    graph.on("tap", "node", (event) => onSelect({ type: "node", id: event.target.id() }));
    graph.on("tap", "edge", (event) => onSelect({ type: "edge", id: event.target.id() }));
    graphRef.current = graph;

    return () => {
      graph.destroy();
      graphRef.current = null;
    };
  }, [elements, onSelect]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || !graph.getElementById(selectedId).length) return;

    graph.elements().removeClass("is-selected is-muted");
    const selected = graph.getElementById(selectedId);
    selected.addClass("is-selected");

    if (selected.isNode()) {
      const neighborhood = selected.closedNeighborhood();
      graph.elements().difference(neighborhood).addClass("is-muted");
    }
  }, [selectedId, elements]);

  return <div className="character-graph" ref={containerRef} aria-label="人物关系图谱" />;
}
