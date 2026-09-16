import { useEffect, useState } from "react";
import {
  Button,
  Column,
  Grid,
  InlineLoading,
  InlineNotification,
  Select,
  SelectItem,
  Tag,
  Tile,
} from "@carbon/react";

import { ApiError, getRevision, getRevisions, runRevision } from "./api";
import type { CaseSnapshot, Revision, RunSummary } from "./api";

function runErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return "This revision is not available.";
    if (error.status === 409) return "Kratos is already running another case.";
    return error.message;
  }
  return error instanceof Error ? error.message : "Unexpected error";
}

interface RevisionPanelProps {
  snapshot: CaseSnapshot | null;
  onRefresh: () => Promise<CaseSnapshot>;
}

export function RevisionPanel({ snapshot, onRefresh }: RevisionPanelProps) {
  const currentRevision = snapshot?.case.revision;
  const [selectedRevision, setSelectedRevision] = useState(currentRevision ?? 0);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [selected, setSelected] = useState<CaseSnapshot | null>(null);
  const [run, setRun] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    if (currentRevision === undefined) return;
    setSelectedRevision(currentRevision);
    getRevisions()
      .then((response) => setRevisions(response.revisions))
      .catch((caught) => setError(runErrorMessage(caught)));
  }, [currentRevision]);

  useEffect(() => {
    if (currentRevision === undefined) return;
    let active = true;
    setSelected(null);
    getRevision(selectedRevision)
      .then((revision) => { if (active) setSelected(revision); })
      .catch((caught) => { if (active) setError(runErrorMessage(caught)); });
    return () => { active = false; };
  }, [selectedRevision, currentRevision]);

  async function handleRun() {
    setRunning(true);
    setError(null);
    setRun(null);
    try {
      setRun(await runRevision(selectedRevision));
    } catch (caught) {
      setError(runErrorMessage(caught));
    } finally {
      setRunning(false);
    }
  }

  async function handleRefresh() {
    setRefreshing(true);
    setError(null);
    try {
      await onRefresh();
      const response = await getRevisions();
      setRevisions(response.revisions);
    } catch (caught) {
      setError(runErrorMessage(caught));
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <Grid fullWidth className="revisions-workspace">
      <Column sm={4} md={3} lg={5}>
        <Tile className="revision-control">
          <div>
            <p className="eyebrow">Immutable bundles</p>
            <h2>Run a revision</h2>
            <p className="panel-intro">
              Run a compiled revision in Kratos. This does not change the current
              model.
            </p>
          </div>

          {snapshot && (
            <dl className="revision-facts">
              <div>
                <dt>Current revision</dt>
                <dd>{snapshot.case.revision}</dd>
              </div>
              <div>
                <dt>Current bundle</dt>
                <dd>
                  <code>{snapshot.bundle_id}</code>
                </dd>
              </div>
            </dl>
          )}

          <Select
            id="revision"
            labelText="Revision"
            helperText="Only published bundles can be run. Drafts are not included."
            value={selectedRevision}
            disabled={!snapshot || running}
            onChange={(event) => {
              setSelectedRevision(Number(event.target.value));
              setRun(null);
              setError(null);
            }}
          >
            {revisions.map(({ revision }) => (
              <SelectItem
                key={revision}
                value={revision}
                text={`Revision ${revision}`}
              />
            ))}
          </Select>

          {selected && (
            <details className="native-details">
              <summary>Revision {selected.case.revision} canonical model</summary>
              <pre className="json-view">{JSON.stringify(selected.case, null, 2)}</pre>
            </details>
          )}

          <div className="revision-actions">
            {running ? (
              <InlineLoading description={`Running revision ${selectedRevision}`} />
            ) : (
              <Button type="button" disabled={!snapshot} onClick={handleRun}>
                Run revision
              </Button>
            )}
            <Button
              type="button"
              kind="ghost"
              disabled={refreshing || running}
              onClick={handleRefresh}
            >
              {refreshing ? "Refreshing…" : "Refresh current"}
            </Button>
          </div>

          {error && (
            <InlineNotification
              kind="error"
              lowContrast
              hideCloseButton
              title="Run failed"
              subtitle={error}
            />
          )}
        </Tile>
      </Column>

      <Column sm={4} md={5} lg={11} className="run-column">
        <Tile className="run-panel">
          <div className="run-panel__heading">
            <div>
              <p className="eyebrow">Kratos worker</p>
              <h2>Latest run</h2>
            </div>
            {run && <Tag type="green">{run.status}</Tag>}
          </div>

          {run ? (
            <div className="run-result">
              <dl className="run-facts">
                <div>
                  <dt>Revision</dt>
                  <dd>{run.case_revision ?? "Original case"}</dd>
                </div>
                <div>
                  <dt>Case</dt>
                  <dd>{run.case}</dd>
                </div>
                <div>
                  <dt>Kratos</dt>
                  <dd>{run.kratos_version}</dd>
                </div>
                <div>
                  <dt>Analysis stage</dt>
                  <dd>{run.analysis_stage}</dd>
                </div>
                <div className="run-facts__wide">
                  <dt>Run ID</dt>
                  <dd>
                    <code>{run.run_id}</code>
                  </dd>
                </div>
              </dl>

              <section className="run-outputs" aria-labelledby="outputs-title">
                <h3 id="outputs-title">Outputs</h3>
                {run.outputs.length > 0 ? (
                  <ul>
                    {run.outputs.map((output) => (
                      <li key={output}>{output}</li>
                    ))}
                  </ul>
                ) : (
                  <p>No output files were reported.</p>
                )}
              </section>

            </div>
          ) : (
            <p className="run-empty">
              Select a revision and run it to see the worker result.
            </p>
          )}
        </Tile>
      </Column>
    </Grid>
  );
}
