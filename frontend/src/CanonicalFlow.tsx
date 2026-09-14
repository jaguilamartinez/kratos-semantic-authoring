import { useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";

import type { CanonicalCase, ScalarValues } from "./api";

const CARD_WIDTH = 280;
const COLUMN_GAP = 32;
const BRANCH_GAP = 80;
const LEAF_START_Y = 280;
const ROW_GAP = 32;

type NodeKind = "case" | "group" | "material" | "process";

type ModelNodeData = Record<string, unknown> & {
  kind: NodeKind;
  title: string;
  caption?: string;
  rows: Array<[string, number]>;
  hasTarget: boolean;
  hasSource: boolean;
};

type ModelNode = Node<ModelNodeData, "model">;

function formatValue(value: number): string {
  return new Intl.NumberFormat("en", {
    maximumSignificantDigits: 10,
  }).format(value);
}

function ModelCard({ data }: NodeProps<ModelNode>) {
  return (
    <article className={`model-card model-card--${data.kind}`}>
      {data.hasTarget && (
        <Handle type="target" position={Position.Top} isConnectable={false} />
      )}
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
      {data.hasSource && (
        <Handle type="source" position={Position.Bottom} isConnectable={false} />
      )}
    </article>
  );
}

const nodeTypes: NodeTypes = { model: ModelCard };

function sortedValues(values: ScalarValues): Array<[string, number]> {
  return Object.entries(values).sort(([left], [right]) =>
    left.localeCompare(right),
  );
}

function nodeHeight(data: ModelNodeData): number {
  return 92 + data.rows.length * 25 + (data.caption ? 28 : 0);
}

function layoutBranch(nodes: ModelNode[], startX: number): ModelNode[] {
  let y = LEAF_START_Y;

  for (let index = 0; index < nodes.length; index += 2) {
    const row = nodes.slice(index, index + 2);
    const height = Math.max(...row.map((node) => nodeHeight(node.data)));

    row.forEach((node, column) => {
      node.position = {
        x: startX + column * (CARD_WIDTH + COLUMN_GAP),
        y,
      };
    });
    y += height + ROW_GAP;
  }

  return nodes;
}

function graphFromCase(model: CanonicalCase): {
  nodes: ModelNode[];
  edges: Edge[];
} {
  const branchWidth = CARD_WIDTH * 2 + COLUMN_GAP;
  const processStartX = branchWidth + BRANCH_GAP;
  const rootX = (branchWidth * 2 + BRANCH_GAP - CARD_WIDTH) / 2;

  const materialNodes = layoutBranch(
    Object.entries(model.materials)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([modelPartName, material]) => ({
        id: `material:${encodeURIComponent(modelPartName)}`,
        type: "model",
        position: { x: 0, y: 0 },
        data: {
          kind: "material",
          title: modelPartName,
          caption: `${Object.keys(material.variables).length} variables`,
          rows: sortedValues(material.variables),
          hasTarget: true,
          hasSource: false,
        },
        ariaLabel: `Material ${modelPartName}`,
        style: { width: CARD_WIDTH },
      })),
    0,
  );

  const processNodes = layoutBranch(
    Object.entries(model.processes)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([processId, process]) => ({
        id: `process:${encodeURIComponent(processId)}`,
        type: "model",
        position: { x: 0, y: 0 },
        data: {
          kind: "process",
          title: process.model_part_name || processId,
          caption: [processId, process.process_name, process.variable_name]
            .filter(Boolean)
            .join(" · "),
          rows: sortedValues(process.parameters),
          hasTarget: true,
          hasSource: false,
        },
        ariaLabel: `Process ${processId}`,
        style: { width: CARD_WIDTH },
      })),
    processStartX,
  );

  const nodes: ModelNode[] = [
    {
      id: "case",
      type: "model",
      position: { x: rootX, y: 0 },
      data: {
        kind: "case",
        title: model.problem_name,
        caption: `Revision ${model.revision} · Units ${model.unit_system}`,
        rows: [],
        hasTarget: false,
        hasSource: true,
      },
      ariaLabel: `Case ${model.problem_name}`,
      style: { width: CARD_WIDTH },
    },
    {
      id: "materials",
      type: "model",
      position: { x: (branchWidth - CARD_WIDTH) / 2, y: 150 },
      data: {
        kind: "group",
        title: "Materials",
        caption: `${materialNodes.length} model parts`,
        rows: [],
        hasTarget: true,
        hasSource: true,
      },
      ariaLabel: "Materials",
      style: { width: CARD_WIDTH },
    },
    {
      id: "processes",
      type: "model",
      position: {
        x: processStartX + (branchWidth - CARD_WIDTH) / 2,
        y: 150,
      },
      data: {
        kind: "group",
        title: "Processes",
        caption: `${processNodes.length} processes`,
        rows: [],
        hasTarget: true,
        hasSource: true,
      },
      ariaLabel: "Processes",
      style: { width: CARD_WIDTH },
    },
    ...materialNodes,
    ...processNodes,
  ];

  const edges: Edge[] = [
    {
      id: "case-materials",
      source: "case",
      target: "materials",
      ariaLabel: "Case materials",
    },
    {
      id: "case-processes",
      source: "case",
      target: "processes",
      ariaLabel: "Case processes",
    },
    ...materialNodes.map((node) => ({
      id: `materials-${node.id}`,
      source: "materials",
      target: node.id,
      ariaLabel: `Materials contains ${node.data.title}`,
    })),
    ...processNodes.map((node) => ({
      id: `processes-${node.id}`,
      source: "processes",
      target: node.id,
      ariaLabel: `Processes contains ${node.data.title}`,
    })),
  ];

  return { nodes, edges };
}

export function CanonicalFlow({ model }: { model: CanonicalCase }) {
  const graph = useMemo(() => graphFromCase(model), [model]);

  return (
    <ReactFlow
      key={model.revision}
      nodes={graph.nodes}
      edges={graph.edges}
      nodeTypes={nodeTypes}
      colorMode="light"
      fitView
      fitViewOptions={{ padding: 0.12 }}
      minZoom={0.25}
      maxZoom={1.5}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      deleteKeyCode={null}
      defaultEdgeOptions={{
        type: "smoothstep",
        markerEnd: { type: MarkerType.ArrowClosed },
      }}
    >
      <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}
