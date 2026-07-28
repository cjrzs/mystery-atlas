"use client";

import cytoscape, { Core } from "cytoscape";
import { useEffect, useMemo, useRef } from "react";
import type { GraphEdge, GraphNode } from "@/lib/api";
import { relationCategory } from "@/lib/graph-labels";

type GraphSelection =
  | { type: "node"; id: string }
  | { type: "edge"; id: string };

type CharacterGraphProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  chapter: number;
  visibleKinds: Set<string>;
  selectedId: string | null;
  onSelect: (selection: GraphSelection) => void;
};

export function CharacterGraph({ nodes, edges, chapter, visibleKinds, selectedId, onSelect }: CharacterGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Core | null>(null);

  const { elements, coreNodeIds } = useMemo(() => {
    const visibleNodes = nodes.filter((node) => node.first_chapter <= chapter);
    const nodeIds = new Set(visibleNodes.map((node) => node.id));
    const visibleEdges = edges.filter((edge) => (
      edge.first_chapter <= chapter
      && nodeIds.has(edge.source)
      && nodeIds.has(edge.target)
      && visibleKinds.has(edge.kind)
    ));
    const degreeByNode = new Map(visibleNodes.map((node) => [node.id, 0]));
    for (const edge of visibleEdges) {
      degreeByNode.set(edge.source, (degreeByNode.get(edge.source) ?? 0) + 1);
      degreeByNode.set(edge.target, (degreeByNode.get(edge.target) ?? 0) + 1);
    }
    const coreCount = visibleNodes.length >= 12 ? 3 : visibleNodes.length >= 5 ? 2 : 1;
    const coreNodeIds = new Set(
      [...visibleNodes]
        .sort((left, right) => (
          (degreeByNode.get(right.id) ?? 0) - (degreeByNode.get(left.id) ?? 0)
          || left.first_chapter - right.first_chapter
          || left.name.localeCompare(right.name, "zh-CN")
        ))
        .slice(0, coreCount)
        .map((node) => node.id),
    );

    return {
      coreNodeIds,
      elements: [
        ...visibleNodes.map((node) => ({
          data: {
            id: node.id,
            label: node.name,
            role: node.role,
            group: node.group,
            degree: degreeByNode.get(node.id) ?? 0,
          },
          classes: `group-${node.group}${coreNodeIds.has(node.id) ? " is-core" : ""}`,
        })),
        ...visibleEdges.map((edge) => ({
          data: { id: edge.id, source: edge.source, target: edge.target, label: edge.label, status: edge.status },
          classes: `kind-${relationCategory(edge.kind)} status-${edge.status}`,
        })),
      ],
    };
  }, [chapter, edges, nodes, visibleKinds]);

  useEffect(() => {
    if (!containerRef.current) return;

    const graph = cytoscape({
      container: containerRef.current,
      elements,
      layout: {
        name: "cose",
        fit: true,
        padding: 50,
        animate: false,
        randomize: true,
        nodeRepulsion: (node) => node.hasClass("is-core") ? 900_000 : 450_000,
        idealEdgeLength: (edge) => (
          coreNodeIds.has(edge.source().id()) || coreNodeIds.has(edge.target().id())
            ? 90
            : 125
        ),
        edgeElasticity: 120,
        nestingFactor: 1.15,
        gravity: 1.2,
        numIter: 1200,
      },
      minZoom: 0.55,
      maxZoom: 1.8,
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
            "font-size": 14,
            "font-weight": 600,
            "text-valign": "bottom",
            "text-margin-y": 8,
            "text-background-color": "#f5f7f8",
            "text-background-opacity": 0.92,
            "text-background-padding": "3px",
            "text-background-shape": "roundrectangle",
            "overlay-opacity": 0,
          },
        },
        {
          selector: "node.is-core",
          style: {
            width: 78,
            height: 78,
            "border-width": 4,
            "border-color": "#087e6d",
            "font-size": 15,
            "font-weight": 700,
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
            "font-size": 12,
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
        { selector: ".kind-romantic", style: { "line-color": "#9a5d79" } },
        { selector: ".kind-friendship", style: { "line-color": "#188675" } },
        { selector: ".kind-professional", style: { "line-color": "#5369a5" } },
        { selector: ".kind-investigation", style: { "line-color": "#188675" } },
        { selector: ".kind-crime", style: { "line-color": "#b45042", width: 2.3 } },
        { selector: ".kind-care", style: { "line-color": "#4f8d7f" } },
        { selector: ".kind-financial", style: { "line-color": "#9d791e" } },
        { selector: ".kind-medical", style: { "line-color": "#5369a5" } },
        { selector: ".kind-legal", style: { "line-color": "#6f6288" } },
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
  }, [coreNodeIds, elements, onSelect]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || !selectedId || !graph.getElementById(selectedId).length) return;

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
