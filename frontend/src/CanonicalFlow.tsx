import { useEffect, useMemo, useState } from "react";
import { Button } from "@carbon/react";
import {
  Background, BackgroundVariant, Controls, Handle, MarkerType, MiniMap,
  Position, ReactFlow, type Edge, type Node, type NodeProps, type NodeTypes,
  type ReactFlowInstance, useNodesState,
} from "@xyflow/react";

import type { CanonicalCase, Component, JsonValue, Settings } from "./api";

const CARD_WIDTH = 280;
const COLUMN_GAP = 100;
const ROW_GAP = 32;

type NodeKind = "case" | "region" | "material" | "boundary" | "load" | "initial" | "output" | "process";

type ModelNodeData = Record<string, unknown> & {
  kind: NodeKind;
  title: string;
  caption?: string;
  rows: Array<[string, JsonValue]>;
};

type ModelNode = Node<ModelNodeData, "model">;

interface ModelGraph {
  nodes: ModelNode[];
  edges: Edge[];
}

function formatValue(value: JsonValue): string {
  if (typeof value === "number") {
    return new Intl.NumberFormat("en", { maximumSignificantDigits: 7 }).format(value);
  }
  return typeof value === "string" ? value : JSON.stringify(value);
}

function ModelCard({ data }: NodeProps<ModelNode>) {
  return (
    <article className={`model-card model-card--${data.kind}`}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <p className="model-card__kind">{data.kind}</p>
      <h3>{data.title}</h3>
      {data.caption && <p className="model-card__caption">{data.caption}</p>}
      {data.rows.length > 0 && (
        <dl className="model-card__values">
          {data.rows.map(([name, value]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{formatValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </article>
  );
}

const nodeTypes: NodeTypes = { model: ModelCard };

function selectedValues(settings: Settings, names: string[]): Array<[string, JsonValue]> {
  return names.filter((name) => name in settings).map((name) => [name, settings[name]]);
}

function graphFromCase(model: CanonicalCase): ModelGraph {
  const nodes: ModelNode[] = [];
  const edges: Edge[] = [];
  const regionIds = new Map<string, string>();

  function addNode(id: string, data: ModelNodeData, x: number, y: number) {
    nodes.push({
      id, type: "model", position: { x, y }, data,
      ariaLabel: `${data.kind} ${data.title}`, style: { width: CARD_WIDTH },
    });
  }

  function connect(source: string, target: string, label: string) {
    edges.push({ id: `${source}-${target}-${edges.length}`, source, target, label });
  }

  addNode("case", {
    kind: "case", title: model.problem_name,
    caption: `Revision ${model.revision} · Units ${model.unit_system}`,
    rows: selectedValues(model.analysis, ["type", "start_time", "end_time"]),
  }, CARD_WIDTH + COLUMN_GAP, 0);

  let materialY = 240;
  for (const [id, material] of Object.entries(model.materials)) {
    const properties = Array.isArray(material.settings.properties) ? {} : material.settings.properties;
    const rows = Object.entries(properties).slice(0, 5);
    addNode(`material:${id}`, {
      kind: "material", title: material.label,
      caption: typeof material.settings.law?.name === "string" ? material.settings.law.name : undefined,
      rows,
    }, 0, materialY);
    materialY += 140 + rows.length * 32 + ROW_GAP;
  }

  let regionY = 240;
  for (const [id, region] of Object.entries(model.model.regions)) {
    const nodeId = `region:${id}`;
    regionIds.set(region.name, nodeId);
    addNode(nodeId, { kind: "region", title: region.name, rows: [] }, CARD_WIDTH + COLUMN_GAP, regionY);
    regionY += 110 + ROW_GAP;
  }

  for (const [id, region] of Object.entries(model.model.regions)) {
    connect(region.parent ? regionIds.get(region.parent) ?? "case" : "case", `region:${id}`, "contains");
  }
  for (const assignment of Object.values(model.material_assignments)) {
    const region = regionIds.get(assignment.region);
    if (region) connect(`material:${assignment.material_id}`, region, `properties ${assignment.properties_id}`);
  }

  let actionY = 240;
  const sections: Array<[NodeKind, Record<string, Component>]> = [
    ["boundary", model.boundary_conditions], ["load", model.loads],
    ["initial", model.initial_conditions], ["output", model.outputs],
    ["process", model.auxiliary_processes],
  ];
  for (const [kind, components] of sections) {
    for (const [id, component] of Object.entries(components)) {
      const settings = component.settings;
      const rows = selectedValues(settings, ["value", "fixed", "magnitude", "direction", "interval", "output_interval"]);
      const nodeId = `${kind}:${id}`;
      addNode(nodeId, {
        kind, title: component.label,
        caption: typeof settings.variable === "string" ? settings.variable : component.capability ?? "Native component",
        rows,
      }, 2 * (CARD_WIDTH + COLUMN_GAP), actionY);
      actionY += 150 + rows.length * 32 + ROW_GAP;
      const region = typeof settings.region === "string" ? regionIds.get(settings.region) : undefined;
      connect(region ?? "case", nodeId, kind === "output" ? "reports" : "applies to");
    }
  }

  return { nodes, edges };
}

function FlowCanvas({ graph }: { graph: ModelGraph }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<ModelNode>(graph.nodes);
  const [flow, setFlow] = useState<ReactFlowInstance<ModelNode, Edge> | null>(null);

  useEffect(() => {
    setNodes((previous) => {
      const positions = new Map(previous.map((node) => [node.id, node.position]));
      return graph.nodes.map((node) => ({ ...node, position: positions.get(node.id) ?? node.position }));
    });
  }, [graph, setNodes]);

  function resetLayout() {
    setNodes(graph.nodes.map((node) => ({ ...node, position: { ...node.position } })));
    requestAnimationFrame(() => { void flow?.fitView({ padding: 0.12, duration: 250 }); });
  }

  return (
    <div className="flow-view">
      <div className="flow-toolbar">
        <p>Materials → regions → conditions, loads and outputs. Drag cards to rearrange the view.</p>
        <Button type="button" kind="ghost" size="sm" onClick={resetLayout}>Reset layout</Button>
      </div>
      <div className="flow-canvas">
        <ReactFlow<ModelNode, Edge>
          nodes={nodes}
          edges={graph.edges}
          nodeTypes={nodeTypes}
          colorMode="light"
          fitView
          fitViewOptions={{ padding: 0.12 }}
          minZoom={0.15}
          maxZoom={1.5}
          onInit={setFlow}
          onNodesChange={onNodesChange}
          nodesDraggable
          nodesConnectable={false}
          edgesFocusable={false}
          edgesReconnectable={false}
          elementsSelectable
          deleteKeyCode={null}
          defaultEdgeOptions={{
            type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed },
            focusable: false, selectable: false,
          }}
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
          <MiniMap ariaLabel="Canonical model overview" pannable zoomable nodeStrokeWidth={3} />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  );
}

export function CanonicalFlow({ model }: { model: CanonicalCase }) {
  const graph = useMemo(() => graphFromCase(model), [model]);
  return <FlowCanvas graph={graph} />;
}
