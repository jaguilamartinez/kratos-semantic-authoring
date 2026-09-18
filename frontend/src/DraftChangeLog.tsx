import { Tag } from "@carbon/react";

import type { DraftChangeSet, FieldChange, JsonValue } from "./api";

function formatValue(value: JsonValue | undefined): string {
  return value === undefined ? "(absent)" : JSON.stringify(value);
}

function ChangeValues({ change }: { change: FieldChange }) {
  return (
    <div className="change-log__values">
      {change.before !== undefined && (
        <div className="change-log__value change-log__value--removed">
          <span>−</span><code>before</code><span>{formatValue(change.before)}</span>
        </div>
      )}
      {change.after !== undefined && (
        <div className="change-log__value change-log__value--added">
          <span>+</span><code>after</code><span>{formatValue(change.after)}</span>
        </div>
      )}
    </div>
  );
}

function ChangeGroup({ title, changes }: { title: string; changes: FieldChange[] }) {
  if (!changes.length) return null;
  return (
    <section className="change-log__group">
      <h4>{title}</h4>
      {changes.map((change, index) => (
        <details className="change-log__field" key={`${change.field}-${index}`}>
          <summary>
            <code>{change.field}</code>
            <Tag size="sm" type={change.operation === "add" ? "green" : change.operation === "remove" ? "red" : "gray"}>
              {change.operation ?? "replace"}
            </Tag>
          </summary>
          <ChangeValues change={change} />
        </details>
      ))}
    </section>
  );
}

export function DraftChangeLog({
  entries,
  currentChanges,
  currentNativeChanges,
}: {
  entries: DraftChangeSet[];
  currentChanges: FieldChange[];
  currentNativeChanges: FieldChange[];
}) {
  const legacyEntry = currentChanges.length || currentNativeChanges.length
    ? [{ sequence: 1, changes: currentChanges, native_changes: currentNativeChanges }]
    : [];
  const changeLog = entries.length ? entries : legacyEntry;

  if (!changeLog.length) {
    return <p className="panel-intro">This draft does not contain model changes yet.</p>;
  }

  return (
    <div className="change-log">
      {changeLog.map((entry, index) => (
        <details className="change-log__entry" key={entry.sequence}
          open={index === changeLog.length - 1}>
          <summary>
            <span>Update {entry.sequence}</span>
            <span>{entry.changes.length} semantic · {entry.native_changes.length} compiled</span>
          </summary>
          <div className="change-log__entry-body">
            <ChangeGroup title="Canonical model" changes={entry.changes} />
            <ChangeGroup title="Compiled files" changes={entry.native_changes} />
          </div>
        </details>
      ))}
    </div>
  );
}
