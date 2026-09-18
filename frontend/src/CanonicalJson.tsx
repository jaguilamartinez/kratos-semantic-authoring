import type { ReactNode } from "react";

import type { CanonicalCase, FieldChange, JsonValue } from "./api";

const MISSING = Symbol("missing");
type MaybeValue = JsonValue | typeof MISSING;
type ChangeKind = "added" | "removed";
type Container = JsonValue[] | { [key: string]: JsonValue };

function isObject(value: MaybeValue): value is { [key: string]: JsonValue } {
  return value !== MISSING && typeof value === "object" && value !== null && !Array.isArray(value);
}

function isContainer(value: MaybeValue): value is Container {
  return value !== MISSING && typeof value === "object" && value !== null;
}

function sameValue(before: MaybeValue, after: MaybeValue): boolean {
  return JSON.stringify(before) === JSON.stringify(after);
}

function entries(value: Container): Array<[string, JsonValue]> {
  return Array.isArray(value)
    ? value.map((item, index) => [String(index), item])
    : Object.entries(value);
}

function keys(before: MaybeValue, after: MaybeValue): string[] {
  const afterKeys = isContainer(after) ? entries(after).map(([key]) => key) : [];
  const beforeKeys = isContainer(before) ? entries(before).map(([key]) => key) : [];
  return [...afterKeys, ...beforeKeys.filter((key) => !afterKeys.includes(key))];
}

function formatValue(value: JsonValue): string {
  return JSON.stringify(value) ?? String(value);
}

function marker(kind?: ChangeKind): string {
  return kind === "added" ? "+" : kind === "removed" ? "−" : "";
}

function ValueRow({
  label,
  value,
  kind,
}: {
  label: string;
  value: JsonValue;
  kind?: ChangeKind;
}) {
  return (
    <div className={`canonical-json__row${kind ? ` canonical-json__row--${kind}` : ""}`}>
      <span className="canonical-json__marker">{marker(kind)}</span>
      <code className="canonical-json__key">{label}</code>
      <span className="canonical-json__value">{formatValue(value)}</span>
    </div>
  );
}

function Group({
  label,
  value,
  path,
  depth,
  kind,
  diff,
}: {
  label: string;
  value: Container;
  path: string;
  depth: number;
  kind?: ChangeKind;
  diff: boolean;
}) {
  const childEntries = entries(value);
  const isArray = Array.isArray(value);
  return (
    <details className={`canonical-json__group${kind ? ` canonical-json__group--${kind}` : ""}`}
      open={depth === 0}>
      <summary className="canonical-json__group-header">
        <span className="canonical-json__marker">{marker(kind)}</span>
        <code className="canonical-json__key">{label}</code>
        <span className="canonical-json__type">{isArray ? `[${value.length}]` : "{}"}</span>
      </summary>
      {childEntries.length > 0 && (
        <div className="canonical-json__children">
          {childEntries.map(([key, child]) => (
            <TreeNode key={`${path}.${key}`} label={isArray ? `[${key}]` : key}
              before={kind === "removed" ? child : MISSING}
              after={kind === "removed" ? MISSING : child}
              path={`${path}.${key}`} depth={depth + 1} diff={diff} forcedKind={kind} />
          ))}
        </div>
      )}
    </details>
  );
}

function ChangedValue({
  label,
  before,
  after,
}: {
  label: string;
  before: JsonValue;
  after: JsonValue;
}) {
  return (
    <div className="canonical-json__change">
      <ValueRow label={label} value={before} kind="removed" />
      <ValueRow label={label} value={after} kind="added" />
    </div>
  );
}

function TreeNode({
  label,
  before,
  after,
  path,
  depth,
  diff,
  forcedKind,
}: {
  label: string;
  before: MaybeValue;
  after: MaybeValue;
  path: string;
  depth: number;
  diff: boolean;
  forcedKind?: ChangeKind;
}): ReactNode {
  if (!diff) {
    if (after === MISSING) return null;
    return isContainer(after)
      ? <Group label={label} value={after} path={path} depth={depth} diff={false} />
      : <ValueRow label={label} value={after} />;
  }

  if (forcedKind) {
    const value = forcedKind === "added" ? after : before;
    if (value === MISSING) return null;
    return isContainer(value)
      ? <Group label={label} value={value} path={path} depth={depth} kind={forcedKind} diff />
      : <ValueRow label={label} value={value} kind={forcedKind} />;
  }

  if (before === MISSING) {
    if (after === MISSING) return null;
    return isContainer(after)
      ? <Group label={label} value={after} path={path} depth={depth} kind="added" diff />
      : <ValueRow label={label} value={after} kind="added" />;
  }
  if (after === MISSING) {
    return isContainer(before)
      ? <Group label={label} value={before} path={path} depth={depth} kind="removed" diff />
      : <ValueRow label={label} value={before} kind="removed" />;
  }
  if (sameValue(before, after)) {
    return <TreeNode label={label} before={before} after={after} path={path}
      depth={depth} diff={false} />;
  }
  if (isObject(before) && isObject(after)) {
    return (
      <details className="canonical-json__group" open={depth === 0}>
        <summary className="canonical-json__group-header">
          <span className="canonical-json__marker" />
          <code className="canonical-json__key">{label}</code>
          <span className="canonical-json__type">{"{}"}</span>
        </summary>
        <div className="canonical-json__children">
          {keys(before, after).map((key) => (
            <TreeNode key={`${path}.${key}`} label={key}
              before={key in before ? before[key] : MISSING}
              after={key in after ? after[key] : MISSING}
              path={`${path}.${key}`} depth={depth + 1} diff />
          ))}
        </div>
      </details>
    );
  }
  return <ChangedValue label={label} before={before} after={after} />;
}

function RootTree({
  before,
  after,
  diff,
}: {
  before: MaybeValue;
  after: JsonValue;
  diff: boolean;
}) {
  const rootBefore = isObject(before) ? before : {};
  const rootAfter = isObject(after) ? after : {};
  return (
    <div className="canonical-json__root">
      {keys(rootBefore, rootAfter).map((key) => (
        <TreeNode key={key} label={key}
          before={key in rootBefore ? rootBefore[key] : MISSING}
          after={key in rootAfter ? rootAfter[key] : MISSING}
          path={key} depth={0} diff={diff} />
      ))}
    </div>
  );
}

export function CanonicalJson({
  model,
  baseline,
  changes = [],
}: {
  model: CanonicalCase;
  baseline?: CanonicalCase;
  changes?: FieldChange[];
}) {
  const diff = !!baseline && changes.length > 0;
  const added = changes.filter((change) => change.operation === "add").length;
  const removed = changes.filter((change) => change.operation === "remove").length;
  const replaced = changes.filter((change) => change.operation === "replace").length;

  return (
    <div className="canonical-json">
      {diff && (
        <div className="canonical-json__legend" aria-label="Proposed change legend">
          <span className="canonical-json__legend-item canonical-json__legend-item--removed">− Removed {removed}</span>
          <span className="canonical-json__legend-item canonical-json__legend-item--added">+ Added {added}</span>
          {replaced > 0 && <span className="canonical-json__legend-item">{replaced} changed</span>}
        </div>
      )}
      <RootTree
        before={diff ? (baseline as unknown as JsonValue) : MISSING}
        after={model as unknown as JsonValue}
        diff={diff}
      />
    </div>
  );
}
