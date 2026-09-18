import { useEffect, useMemo, useState } from "react";
import { Button } from "@carbon/react";
import {
  Background, BackgroundVariant, Controls, Handle, MarkerType, MiniMap,
  Position, ReactFlow, type Edge, type Node, type NodeProps, type NodeTypes,
  type ReactFlowInstance, useNodesState,
} from "@xyflow/react";

import type { CanonicalCase, Component, FieldChange, JsonValue, Settings } from "./api";

const CARD_WIDTH = 232;
const PAIR_GAP = 52;
const PAIR_WIDTH = 2 * CARD_WIDTH + PAIR_GAP;
const PAIR_COLUMNS = 2;
const PAIR_COLUMN_GAP = 36;
const PAIR_ROW_GAP = 36;
const TOPIC_WIDTH = 164;
const TOPIC_HEIGHT = 84;
const TOPIC_GAP = 72;
const ROOT_WIDTH = 244;
const ROOT_GAP = 96;
const FRAME_PADDING = 28;
const FRAME_HEADER = 64;
const PAIRS_WIDTH = PAIR_COLUMNS * PAIR_WIDTH
  + (PAIR_COLUMNS - 1) * PAIR_COLUMN_GAP;
const FRAME_WIDTH = TOPIC_WIDTH + TOPIC_GAP + PAIRS_WIDTH + 2 * FRAME_PADDING;
const FRAME_GAP = 48;
const NO_CHANGES: FieldChange[] = [];

type Category = "material" | "boundary" | "load" | "output";
type NodeKind = "region" | Category;
type CardRole = "middle" | "target";
type Region = CanonicalCase["model"]["regions"][string];
type ChangeState = "added" | "removed" | "changed";

interface DiffRow {
  field: string;
  before?: JsonValue;
  after?: JsonValue;
  operation: FieldChange["operation"];
}

interface CategoryConfig {
  label: string;
  title: string;
  description: string;
  regionLabel: string;
}

const CATEGORY_ORDER: Category[] = ["material", "boundary", "load", "output"];
const CATEGORIES: Record<Category, CategoryConfig> = {
  material: {
    label: "Materials",
    title: "Materials and element regions",
    description: "Material definitions assigned to volume or element regions.",
    regionLabel: "Element region",
  },
  boundary: {
    label: "Boundary conditions",
    title: "Boundary conditions",
    description: "Constraints applied to boundary regions.",
    regionLabel: "Constrained boundary",
  },
  load: {
    label: "Loads",
    title: "Loads",
    description: "Point and surface loads applied to boundary regions.",
    regionLabel: "Loaded boundary",
  },
  output: {
    label: "Outputs",
    title: "Outputs",
    description: "Result writers attached to reported regions.",
    regionLabel: "Reported region",
  },
};

type ModelNodeData = Record<string, unknown> & {
  category: Category;
  kind: NodeKind;
  role: CardRole;
  title: string;
  caption?: string;
  rows: Array<[string, JsonValue]>;
  changeState?: ChangeState;
  diffRows: DiffRow[];
};

type FrameNodeData = Record<string, unknown> & {
  category: Category;
  title: string;
  description: string;
  count: number;
};

type StructureNodeData = Record<string, unknown> & {
  title: string;
  caption: string;
  rows: Array<[string, JsonValue]>;
  changeState?: ChangeState;
  diffRows: DiffRow[];
};

type TopicNodeData = Record<string, unknown> & {
  category: Category;
  title: string;
  count: number;
};

type ModelNode = Node<ModelNodeData, "model">;
type FrameNode = Node<FrameNodeData, "category-frame">;
type StructureNode = Node<StructureNodeData, "structure">;
type TopicNode = Node<TopicNodeData, "topic">;
type GraphNode = ModelNode | FrameNode | StructureNode | TopicNode;
type ModelEdge = Edge<{
  category: Category;
  kind: "hierarchy" | "relation";
  changeState?: ChangeState;
}>;

interface Pair {
  id: string;
  category: Category;
  source?: ModelNodeData;
  target: ModelNodeData;
  label: string;
  sortKey: string;
  changeState?: ChangeState;
}

interface ModelGraph {
  nodes: GraphNode[];
  edges: ModelEdge[];
}

function formatValue(value: JsonValue): string {
  if (typeof value === "number") {
    return new Intl.NumberFormat("en", { maximumSignificantDigits: 7 }).format(value);
  }
  return typeof value === "string" ? value : JSON.stringify(value);
}

function ModelCard({ data }: NodeProps<ModelNode>) {
  return (
    <article className={`model-card model-card--kind-${data.kind} model-card--category-${data.category}`
      + (data.changeState ? ` model-card--change-${data.changeState}` : "")}>
      {(data.role === "target" || data.role === "middle") && (
        <Handle id={data.role === "middle" ? "hierarchy-target" : "relation-target"}
          className="model-handle" type="target"
          position={Position.Left} isConnectable={false} />
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
      <ModelDiff rows={data.diffRows} />

      {data.role === "middle" && (
        <Handle id="relation-source" className="model-handle" type="source"
          position={Position.Right} isConnectable={false} />
      )}
    </article>
  );
}

function StructureCard({ data }: NodeProps<StructureNode>) {
  return (
    <article className={`structure-card${data.changeState ? ` structure-card--change-${data.changeState}` : ""}`}>
      <p className="model-card__kind">Structure</p>
      <h3>{data.title}</h3>
      <p className="model-card__caption">{data.caption}</p>
      <dl className="model-card__values">
        {data.rows.map(([name, value]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd>{formatValue(value)}</dd>
          </div>
        ))}
      </dl>
      <ModelDiff rows={data.diffRows} />
      <Handle id="root-source" className="model-handle" type="source"
        position={Position.Right} isConnectable={false} />
    </article>
  );
}

function TopicCard({ data }: NodeProps<TopicNode>) {
  return (
    <article className={`topic-card topic-card--${data.category}`}>
      <Handle id="topic-target" className="model-handle" type="target"
        position={Position.Left} isConnectable={false} />
      <p>{data.title}</p>
      <span>{data.count} {data.count === 1 ? "item" : "items"}</span>
      <Handle id="topic-source" className="model-handle" type="source"
        position={Position.Right} isConnectable={false} />
    </article>
  );
}

function CategoryFrame({ data }: NodeProps<FrameNode>) {
  return (
    <section className={`category-frame category-frame--${data.category}`} aria-hidden="true">
      <div>
        <p>{data.title}</p>
        <span>{data.description}</span>
      </div>
      <strong>{data.count}</strong>
    </section>
  );
}

const nodeTypes: NodeTypes = {
  model: ModelCard,
  structure: StructureCard,
  topic: TopicCard,
  "category-frame": CategoryFrame,
};

function selectedValues(settings: Settings, names: string[]): Array<[string, JsonValue]> {
  return names.filter((name) => name in settings).map((name) => [name, settings[name]]);
}

function pathMatches(change: FieldChange, prefix: string): boolean {
  return change.field === prefix || change.field.startsWith(`${prefix}.`);
}

function changesForPaths(changes: FieldChange[], prefixes: string[]): FieldChange[] {
  return changes.filter((change) => prefixes.some((prefix) => pathMatches(change, prefix)));
}

function relativeField(change: FieldChange, prefixes: string[]): string {
  const prefix = prefixes.find((candidate) => pathMatches(change, candidate));
  if (!prefix || change.field === prefix) return "entity";
  return change.field.slice(prefix.length + 1);
}

function changeRows(changes: FieldChange[], prefixes: string[]): DiffRow[] {
  return changes.map((change) => {
    const field = relativeField(change, prefixes);
    const entity = field === "entity";
    return {
      field,
      before: entity ? "entire entity" : change.before,
      after: entity ? "entire entity" : change.after,
      operation: change.operation,
    };
  });
}

function changeState(changes: FieldChange[], prefixes: string[]): ChangeState | undefined {
  if (!changes.length) return undefined;
  const entityChange = changes.find((change) => prefixes.includes(change.field));
  if (entityChange?.operation === "add") return "added";
  if (entityChange?.operation === "remove") return "removed";
  return "changed";
}

function combineChangeStates(states: Array<ChangeState | undefined>): ChangeState | undefined {
  const present = states.filter((state): state is ChangeState => !!state);
  if (!present.length) return undefined;
  if (present.includes("removed")) return "removed";
  if (present.includes("added")) return "added";
  return "changed";
}

function changeValue(value: JsonValue | undefined): string {
  return value === undefined ? "(absent)" : JSON.stringify(value) ?? String(value);
}

function ModelDiff({ rows }: { rows: DiffRow[] }) {
  if (!rows.length) return null;
  return (
    <div className="model-card__diff" aria-label="Proposed changes">
      {rows.map((row, index) => (
        <div className="model-card__diff-group" key={`${row.field}-${index}`}>
          {row.operation !== "add" && (
            <div className="model-card__diff-row model-card__diff-row--removed">
              <span>−</span><code>{row.field}</code><b>{changeValue(row.before)}</b>
            </div>
          )}
          {row.operation !== "remove" && (
            <div className="model-card__diff-row model-card__diff-row--added">
              <span>+</span><code>{row.field}</code><b>{changeValue(row.after)}</b>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function cardHeight(data: { caption?: string; rows: Array<[string, JsonValue]>; diffRows: DiffRow[] }): number {
  return 84 + (data.caption ? 28 : 0) + data.rows.length * 32 + data.diffRows.length * 56;
}

interface RegionRef {
  key: string;
  value: Region;
}

function regionCard(
  region: RegionRef,
  category: Category,
  changes: FieldChange[],
  extraPaths: string[] = [],
): ModelNodeData {
  const regionPath = `model.regions.${region.key}`;
  const regionChanges = changesForPaths(changes, [regionPath]);
  const relationChanges = changesForPaths(changes, extraPaths);
  const parent = region.value.parent ? ` · part of ${region.value.parent}` : " · model root";
  return {
    category,
    kind: "region",
    role: "middle",
    title: region.value.name.split(".").at(-1) ?? region.value.name,
    caption: `${CATEGORIES[category].regionLabel}${parent}`,
    rows: [["mesh assets", region.value.mesh_ids.length]],
    changeState: changeState(regionChanges, [regionPath])
      ?? (relationChanges.length ? "changed" : undefined),
    diffRows: changeRows(regionChanges, [regionPath]),
  };
}

function componentCard(
  component: Component,
  category: Exclude<Category, "material">,
  path: string,
  changes: FieldChange[],
): ModelNodeData {
  const matchingChanges = changesForPaths(changes, [path]);
  return {
    category,
    kind: category,
    role: "target",
    title: component.label,
    caption: typeof component.settings.variable === "string"
      ? component.settings.variable
      : component.capability ?? "Native component",
    rows: selectedValues(component.settings, [
      "value", "fixed", "magnitude", "direction", "interval", "output_interval",
    ]),
    changeState: changeState(matchingChanges, [path]),
    diffRows: changeRows(matchingChanges, [path]),
  };
}

function sortPairs(pairs: Record<Category, Pair[]>): void {
  for (const category of CATEGORY_ORDER) {
    pairs[category].sort((left, right) => {
      return left.sortKey.localeCompare(right.sortKey, undefined, { numeric: true, sensitivity: "base" })
        || left.target.title.localeCompare(right.target.title, undefined, { numeric: true });
    });
  }
}

function pairsFromCase(model: CanonicalCase, changes: FieldChange[]): Record<Category, Pair[]> {
  const pairs: Record<Category, Pair[]> = { material: [], boundary: [], load: [], output: [] };
  const regions = new Map<string, RegionRef>(
    Object.entries(model.model.regions).map(([key, value]) => [value.name, { key, value }]),
  );

  for (const assignment of Object.values(model.material_assignments)) {
    const material = model.materials[assignment.material_id];
    const region = regions.get(assignment.region);
    if (!material || !region) continue;
    const properties = Array.isArray(material.settings.properties) ? {} : material.settings.properties;
    const law = material.settings.law?.name;
    const materialPath = `materials.${assignment.material_id}`;
    const assignmentPath = `material_assignments.${assignment.id}`;
    const materialChanges = changesForPaths(changes, [materialPath]);
    const assignmentChanges = changesForPaths(changes, [assignmentPath]);
    const cardChanges = [...materialChanges, ...assignmentChanges];
    pairs.material.push({
      id: assignment.id,
      category: "material",
      label: `uses properties ${assignment.properties_id}`,
      sortKey: region.value.name,
      source: region.value.parent ? regionCard(region, "material", changes, [assignmentPath]) : undefined,
      target: {
        category: "material",
        kind: "material",
        role: "target",
        title: material.label,
        caption: `${typeof law === "string" ? law : "Material"} · properties ${assignment.properties_id}`,
        rows: Object.entries(properties).slice(0, 4),
        changeState: changeState(materialChanges, [materialPath])
          ?? changeState(assignmentChanges, [assignmentPath]),
        diffRows: changeRows(cardChanges, [materialPath, assignmentPath]),
      },
      changeState: combineChangeStates([
        changeState(materialChanges, [materialPath]),
        changeState(assignmentChanges, [assignmentPath]),
        changeState(changesForPaths(changes, [`model.regions.${region.key}`]), [`model.regions.${region.key}`]),
      ]),
    });
  }

  const componentGroups: Array<[
    Exclude<Category, "material">,
    Record<string, Component>,
  ]> = [
    ["boundary", model.boundary_conditions],
    ["load", model.loads],
    ["output", model.outputs],
  ];
  for (const [category, components] of componentGroups) {
    for (const [id, component] of Object.entries(components)) {
      const regionName = typeof component.settings.region === "string" ? component.settings.region : undefined;
      const region = regionName ? regions.get(regionName) : undefined;
      if (!region) continue;
      const section = {
        boundary: "boundary_conditions",
        load: "loads",
        output: "outputs",
      }[category];
      const componentPath = `${section}.${id}`;
      const componentChanges = changesForPaths(changes, [componentPath]);
      pairs[category].push({
        id,
        category,
        label: CATEGORIES[category].label,
        sortKey: region.value.name,
        source: region.value.parent ? regionCard(region, category, changes, [componentPath]) : undefined,
        target: componentCard(component, category, componentPath, changes),
        changeState: combineChangeStates([
          changeState(componentChanges, [componentPath]),
          changeState(changesForPaths(changes, [`model.regions.${region.key}`]), [`model.regions.${region.key}`]),
        ]),
      });
    }
  }

  sortPairs(pairs);
  return pairs;
}

function pairsForGraph(
  model: CanonicalCase,
  baseline: CanonicalCase | undefined,
  changes: FieldChange[],
): Record<Category, Pair[]> {
  const pairs = pairsFromCase(model, changes);
  if (!baseline || !changes.length) return pairs;

  const previousPairs = pairsFromCase(baseline, changes);
  for (const category of CATEGORY_ORDER) {
    const currentIds = new Set(pairs[category].map((pair) => pair.id));
    for (const pair of previousPairs[category]) {
      if (!currentIds.has(pair.id)) {
        pairs[category].push({ ...pair, changeState: "removed" });
      }
    }
  }
  sortPairs(pairs);
  return pairs;
}

function pairHeight(pair: Pair): number {
  return Math.max(pair.source ? cardHeight(pair.source) : 0, cardHeight(pair.target));
}

function frameHeight(pairs: Pair[]): number {
  let contentHeight = 0;
  for (let index = 0; index < pairs.length; index += PAIR_COLUMNS) {
    const row = pairs.slice(index, index + PAIR_COLUMNS);
    contentHeight += Math.max(...row.map(pairHeight));
    if (index + PAIR_COLUMNS < pairs.length) contentHeight += PAIR_ROW_GAP;
  }
  return FRAME_HEADER + 2 * FRAME_PADDING + Math.max(TOPIC_HEIGHT, contentHeight);
}

function findRootRegion(model: CanonicalCase): RegionRef | undefined {
  const regions = Object.entries(model.model.regions).map(([key, value]) => ({ key, value }));
  return regions.find((region) => region.value.parent === null) ?? regions[0];
}

function structureData(model: CanonicalCase, changes: FieldChange[]): StructureNodeData {
  const root = findRootRegion(model);
  if (!root) {
    return {
      title: model.problem_name,
      caption: "Root model part",
      rows: [["regions", Object.keys(model.model.regions).length]],
      diffRows: [],
    };
  }

  const path = `model.regions.${root.key}`;
  const matchingChanges = changesForPaths(changes, [path]);
  const childCount = Object.values(model.model.regions)
    .filter((region) => region.parent === root.value.name).length;
  return {
    title: root.value.name,
    caption: "Root model part",
    rows: [
      ["mesh assets", root.value.mesh_ids.length],
      ["child regions", childCount],
    ],
    changeState: changeState(matchingChanges, [path]),
    diffRows: changeRows(matchingChanges, [path]),
  };
}

function graphFromCase(
  model: CanonicalCase,
  baseline: CanonicalCase | undefined,
  changes: FieldChange[],
): ModelGraph {
  const nodes: GraphNode[] = [];
  const edges: ModelEdge[] = [];
  const pairs = pairsForGraph(model, baseline, changes);
  const heights = new Map(CATEGORY_ORDER.map((category) => [category, frameHeight(pairs[category])]));
  const categoryY = new Map<Category, number>();
  let nextY = 0;
  for (const category of CATEGORY_ORDER) {
    categoryY.set(category, nextY);
    nextY += (heights.get(category) ?? 0) + FRAME_GAP;
  }
  const totalHeight = Math.max(0, nextY - FRAME_GAP);
  const rootData = structureData(model, changes);
  const rootId = "structure:root";
  const frameX = ROOT_WIDTH + ROOT_GAP;

  nodes.push({
    id: rootId,
    type: "structure",
    position: { x: 0, y: Math.max(0, (totalHeight - cardHeight(rootData)) / 2) },
    data: rootData,
    zIndex: 3,
    ariaLabel: `Structure ${rootData.title}`,
    style: { width: ROOT_WIDTH },
  });

  function addCard(id: string, data: ModelNodeData, x: number, y: number) {
    nodes.push({
      id,
      type: "model",
      position: { x, y },
      data,
      zIndex: 2,
      ariaLabel: `${data.kind} ${data.title}`,
      style: { width: CARD_WIDTH },
    });
  }

  function connect({
    id, category, kind, source, target, sourceHandle, targetHandle, label, state,
  }: {
    id: string;
    category: Category;
    kind: "hierarchy" | "relation";
    source: string;
    target: string;
    sourceHandle: string;
    targetHandle: string;
    label?: string;
    state?: ChangeState;
  }) {
    const color = state === "added" ? "var(--ksa-diff-added)"
      : state === "removed" ? "var(--ksa-diff-removed)"
        : `var(--ksa-edge-${category})`;
    const changeClass = state ? ` model-edge--change-${state}` : "";
    const edgeLabel = state === "added" && label ? `+ ${label}`
      : state === "removed" && label ? `− ${label}` : label;
    edges.push({
      id,
      source,
      target,
      sourceHandle,
      targetHandle,
      label: edgeLabel,
      data: { category, kind, changeState: state },
      className: `model-edge model-edge--${kind} model-edge--${category}${changeClass}`,
      type: "smoothstep",
      interactionWidth: 20,
      style: {
        stroke: color,
        strokeWidth: state ? 2.4 : kind === "hierarchy" ? 1.4 : 1.7,
        strokeDasharray: state === "removed" ? "6 4" : undefined,
      },
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
      labelStyle: edgeLabel ? { fill: color, fontSize: 11, fontWeight: 600 } : undefined,
      labelBgStyle: edgeLabel ? { fill: "var(--ksa-edge-label)", fillOpacity: 0.94 } : undefined,
      labelBgPadding: edgeLabel ? [5, 3] : undefined,
      labelBgBorderRadius: edgeLabel ? 2 : undefined,
    });
  }

  function placeCategory(category: Category, x: number, y: number) {
    const categoryPairs = pairs[category];
    const height = heights.get(category) ?? 0;
    const config = CATEGORIES[category];
    nodes.push({
      id: `frame:${category}`,
      type: "category-frame",
      position: { x, y },
      data: {
        category,
        title: config.title,
        description: config.description,
        count: categoryPairs.length,
      },
      draggable: false,
      selectable: false,
      focusable: false,
      style: { width: FRAME_WIDTH, height },
      zIndex: 0,
    });

    const topicId = `topic:${category}`;
    const contentHeight = height - FRAME_HEADER - 2 * FRAME_PADDING;
    nodes.push({
      id: topicId,
      type: "topic",
      position: {
        x: x + FRAME_PADDING,
        y: y + FRAME_HEADER + FRAME_PADDING + (contentHeight - TOPIC_HEIGHT) / 2,
      },
      data: { category, title: config.label, count: categoryPairs.length },
      zIndex: 2,
      ariaLabel: `${config.label}, ${categoryPairs.length} items`,
      style: { width: TOPIC_WIDTH },
    });
    connect({
      id: `hierarchy:root:${category}`,
      category,
      kind: "hierarchy",
      source: rootId,
      target: topicId,
      sourceHandle: "root-source",
      targetHandle: "topic-target",
    });

    let rowY = y + FRAME_HEADER + FRAME_PADDING;
    for (let index = 0; index < categoryPairs.length; index += PAIR_COLUMNS) {
      const row = categoryPairs.slice(index, index + PAIR_COLUMNS);
      const rowHeight = Math.max(...row.map(pairHeight));
      row.forEach((pair, column) => {
        const pairX = x + FRAME_PADDING + TOPIC_WIDTH + TOPIC_GAP
          + column * (PAIR_WIDTH + PAIR_COLUMN_GAP);
        const sourceId = `${category}:region:${pair.id}`;
        const targetId = `${category}:target:${pair.id}`;
        addCard(targetId, pair.target, pairX + CARD_WIDTH + PAIR_GAP,
          rowY + (rowHeight - cardHeight(pair.target)) / 2);
        if (pair.source) {
          addCard(sourceId, pair.source, pairX, rowY + (rowHeight - cardHeight(pair.source)) / 2);
          connect({
            id: `hierarchy:${category}:${pair.id}`,
            category,
            kind: "hierarchy",
            source: topicId,
            target: sourceId,
            sourceHandle: "topic-source",
            targetHandle: "hierarchy-target",
            state: pair.changeState,
          });
          connect({
            id: `relation:${category}:${pair.id}`,
            category,
            kind: "relation",
            source: sourceId,
            target: targetId,
            sourceHandle: "relation-source",
            targetHandle: "relation-target",
            label: pair.label,
            state: pair.changeState,
          });
        } else {
          connect({
            id: `relation:${category}:${pair.id}`,
            category,
            kind: "relation",
            source: topicId,
            target: targetId,
            sourceHandle: "topic-source",
            targetHandle: "relation-target",
            label: pair.label,
            state: pair.changeState,
          });
        }
      });
      rowY += rowHeight + PAIR_ROW_GAP;
    }
  }

  CATEGORY_ORDER.forEach((category) => placeCategory(category, frameX, categoryY.get(category) ?? 0));

  return { nodes, edges };
}

function FlowCanvas({ graph }: { graph: ModelGraph }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<GraphNode>(graph.nodes);
  const [flow, setFlow] = useState<ReactFlowInstance<GraphNode, ModelEdge> | null>(null);
  const [activeCategory, setActiveCategory] = useState<Category | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const activeNode = hoveredNode ?? selectedNode;
  const hasProposedChanges = graph.edges.some((edge) => (
    (!activeCategory || edge.data?.category === activeCategory) && edge.data?.changeState
  )) || graph.nodes.some((node) => (
    (!activeCategory || node.id === "structure:root" || node.data.category === activeCategory)
      && node.data.changeState
  ));

  useEffect(() => {
    setNodes(graph.nodes);
  }, [graph, setNodes]);

  function visibleCategoryNodes(sourceNodes: GraphNode[], category: Category | null): GraphNode[] {
    if (!category) return sourceNodes;

    const visible = sourceNodes.filter(
      (node) => node.id === "structure:root" || node.data.category === category,
    );
    const frame = visible.find((node) => node.id === `frame:${category}`);
    const root = visible.find((node): node is StructureNode => node.type === "structure");
    const frameHeight = typeof frame?.style?.height === "number" ? frame.style.height : 0;
    if (!frame || !root || !frameHeight) return visible;

    const rootY = frame.position.y + Math.max(0, (frameHeight - cardHeight(root.data)) / 2);
    return visible.map((node) => node.id === root.id
      ? { ...node, position: { ...node.position, y: rootY }, draggable: false }
      : node);
  }

  function focusNodes(sourceNodes: GraphNode[], category: Category | null): GraphNode[] {
    const visible = visibleCategoryNodes(sourceNodes, category);
    if (!category) return visible;
    const cards = visible.filter((node) => node.type !== "category-frame");
    return cards.length > 0 ? cards : visible;
  }

  function fitCategory(instance: ReactFlowInstance<GraphNode, ModelEdge> | null,
                       sourceNodes: GraphNode[], category: Category | null, duration = 250) {
    const visible = focusNodes(sourceNodes, category);
    void instance?.fitView({
      nodes: visible,
      padding: category ? 0.12 : 0.05,
      maxZoom: category ? 0.9 : 0.52,
      duration,
    });
  }

  useEffect(() => {
    if (!flow) return;
    requestAnimationFrame(() => fitCategory(flow, nodes, activeCategory));
  }, [activeCategory, flow]);

  useEffect(() => {
    if (!flow) return;
    requestAnimationFrame(() => fitCategory(flow, graph.nodes, activeCategory));
  }, [flow, graph]);

  const visibleEdges = useMemo(
    () => activeCategory
      ? graph.edges.filter((edge) => edge.data?.category === activeCategory)
      : graph.edges,
    [activeCategory, graph.edges],
  );

  const relatedNodes = useMemo(() => {
    const related = new Set(activeNode ? [activeNode] : []);
    if (!activeNode) return related;

    let current = activeNode;
    while (current) {
      const parentEdge = visibleEdges.find((edge) => edge.target === current);
      if (!parentEdge || related.has(parentEdge.source)) break;
      related.add(parentEdge.source);
      current = parentEdge.source;
    }

    const descendants = [activeNode];
    while (descendants.length) {
      const parent = descendants.shift();
      for (const edge of visibleEdges) {
        if (edge.source !== parent || related.has(edge.target)) continue;
        related.add(edge.target);
        descendants.push(edge.target);
      }
    }
    return related;
  }, [activeNode, visibleEdges]);

  const displayNodes = useMemo(() => visibleCategoryNodes(nodes, activeCategory).map((node) => {
    if (!activeNode || node.type === "category-frame") return node;
    const state = relatedNodes.has(node.id) ? "is-related" : "is-muted";
    return { ...node, className: `${node.className ?? ""} ${state}`.trim() };
  }), [activeCategory, activeNode, nodes, relatedNodes]);

  const displayEdges = useMemo(() => visibleEdges.map((edge) => {
    if (!activeNode) return edge;
    const state = relatedNodes.has(edge.source) && relatedNodes.has(edge.target)
      ? "is-related" : "is-muted";
    return { ...edge, className: `${edge.className ?? ""} ${state}`.trim() };
  }), [activeNode, relatedNodes, visibleEdges]);

  function filterBy(category: Category) {
    setSelectedNode(null);
    setActiveCategory((current) => current === category ? null : category);
  }

  function resetLayout() {
    setSelectedNode(null);
    const resetNodes = graph.nodes.map((node) => ({ ...node, position: { ...node.position } }));
    setNodes(resetNodes);
    requestAnimationFrame(() => fitCategory(flow, resetNodes, activeCategory));
  }

  return (
    <div className="flow-view">
      <div className="flow-toolbar">
        <div className="flow-toolbar__guide">
          <p>Filter by domain. Select the active filter again to return to the complete model.</p>
          <div className="flow-toolbar__filters" aria-label="Model view filters">
            {CATEGORY_ORDER.map((category) => (
              <Button key={category} type="button" size="sm"
                kind={activeCategory === category ? "secondary" : "ghost"}
                className={`flow-filter flow-filter--${category}`}
                aria-pressed={activeCategory === category}
                onClick={() => filterBy(category)}>
                <span className="flow-filter__swatch" />{CATEGORIES[category].label}
              </Button>
            ))}
          </div>
          {hasProposedChanges && (
            <div className="flow-diff-legend" aria-label="Proposed change legend">
              <span className="flow-diff-legend__removed">− Removed</span>
              <span className="flow-diff-legend__added">+ Added</span>
              <span>Changed values show both lines</span>
            </div>
          )}
        </div>
        <Button type="button" kind="ghost" size="sm" onClick={resetLayout}>Reset layout</Button>
      </div>
      <div className="flow-canvas">
        <ReactFlow<GraphNode, ModelEdge>
          nodes={displayNodes}
          edges={displayEdges}
          nodeTypes={nodeTypes}
          colorMode="light"
          minZoom={0.12}
          maxZoom={1.5}
          onInit={setFlow}
          onNodesChange={onNodesChange}
          onNodeMouseEnter={(_, node) => {
            if (node.type !== "category-frame") setHoveredNode(node.id);
          }}
          onNodeMouseLeave={() => setHoveredNode(null)}
          onNodeClick={(_, node) => {
            if (node.type !== "category-frame") setSelectedNode(node.id);
          }}
          onPaneClick={() => setSelectedNode(null)}
          nodesDraggable
          nodesConnectable={false}
          edgesFocusable={false}
          edgesReconnectable={false}
          elementsSelectable
          deleteKeyCode={null}
          defaultEdgeOptions={{ focusable: false, selectable: false }}
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
          {!activeCategory && (
            <MiniMap ariaLabel="Canonical model overview" position="top-right" pannable zoomable nodeStrokeWidth={2}
              nodeColor={(node) => node.type === "category-frame" ? "#f4f4f4"
                : node.type === "structure" ? "#161616"
                  : node.type === "topic" ? "#525252" : "#8d8d8d"} />
          )}
          <Controls />
        </ReactFlow>
      </div>
    </div>
  );
}

export function CanonicalFlow({
  model,
  baseline,
  changes = NO_CHANGES,
}: {
  model: CanonicalCase;
  baseline?: CanonicalCase;
  changes?: FieldChange[];
}) {
  const graph = useMemo(() => graphFromCase(model, baseline, changes), [model, baseline, changes]);
  return <FlowCanvas graph={graph} />;
}
