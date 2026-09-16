import { useEffect, useState, type FormEvent } from "react";
import {
  Button, Column, Grid, InlineLoading, InlineNotification, Select, SelectItem,
  SkeletonText, Stack, Tab, TabList, TabPanel, TabPanels, Tabs, Tag, TextArea, Tile,
} from "@carbon/react";

import {
  ApiError, editCase, getCase, getCoverage, getDraft, getDrafts,
  publishDraft, validateDraft,
} from "./api";
import type { CaseSnapshot, Draft, FieldChange, JsonValue, ValidationReport } from "./api";
import { CanonicalFlow } from "./CanonicalFlow";
import { RevisionPanel } from "./RevisionPanel";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error";
}

function displayValue(value: JsonValue | undefined): string {
  return value === undefined ? "(absent)" : JSON.stringify(value);
}

function Changes({ changes }: { changes: FieldChange[] }) {
  if (!changes.length) return <p className="panel-intro">No changes.</p>;
  return (
    <ul className="change-list">
      {changes.map((change) => (
        <li key={change.field}>
          <code>{change.field}</code>
          <span>{displayValue(change.before)} → {displayValue(change.after)}</span>
        </li>
      ))}
    </ul>
  );
}

function Validation({ report }: { report: ValidationReport }) {
  return (
    <div className="validation-result">
      <Tag type={report.valid ? "green" : "red"}>
        {report.valid ? "Configuration valid" : "Changes needed"}
      </Tag>
      {report.native_check && report.native_check !== "not_run" && (
        <Tag type={report.native_check === "passed" ? "green" : "red"}>
          Kratos check {report.native_check}
        </Tag>
      )}
      {!report.execution_supported && (
        <p className="panel-intro">This configuration is preserved, but execution is not supported by the current profile.</p>
      )}
      {report.issues.length > 0 && (
        <ul className="validation-issues">
          {report.issues.map((issue, index) => (
            <li key={`${issue.path}-${index}`}>
              <strong>{issue.level === "error" ? "Error" : "Note"}</strong>: {issue.message}
              <code>{issue.path}</code>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState<CaseSnapshot | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [coverage, setCoverage] = useState<ValidationReport | null>(null);
  const [prompt, setPrompt] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"editing" | "validating" | "publishing" | "loading" | null>(null);

  async function loadCurrentCase() {
    const current = await getCase();
    setSnapshot(current);
    return current;
  }

  async function loadDrafts() {
    const response = await getDrafts();
    setDrafts(response.drafts.filter((item) => item.status === "editing"));
  }

  useEffect(() => {
    Promise.all([loadCurrentCase(), loadDrafts()])
      .catch((caught) => setError(errorMessage(caught)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!snapshot) return;
    let active = true;
    setCoverage(null);
    getCoverage(draft?.id)
      .then((report) => { if (active) setCoverage(report); })
      .catch((caught) => { if (active) setError(errorMessage(caught)); });
    return () => { active = false; };
  }, [snapshot, draft?.id, draft?.content_hash]);

  async function handleError(caught: unknown) {
    if (caught instanceof ApiError && caught.status === 409) {
      await Promise.all([
        loadCurrentCase(), loadDrafts(),
        draft ? getDraft(draft.id).then(setDraft) : Promise.resolve(),
      ]);
      setError("The case or draft changed elsewhere. Your draft is preserved; review the refreshed state before continuing.");
    } else {
      setError(errorMessage(caught));
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!snapshot || !prompt.trim()) return;
    setBusy("editing");
    setError(null);
    setMessage(null);
    try {
      const response = await editCase(
        prompt.trim(), draft?.base_revision ?? snapshot.case.revision, draft?.id, draft?.content_hash,
      );
      if (response.draft) {
        setDraft(response.draft);
        setPrompt("");
        await loadDrafts();
      }
      setMessage(response.message);
    } catch (caught) {
      await handleError(caught);
    } finally {
      setBusy(null);
    }
  }

  async function selectDraft(id: string) {
    setError(null);
    setMessage(null);
    if (!id) { setDraft(null); return; }
    setBusy("loading");
    try { setDraft(await getDraft(id)); }
    catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(null); }
  }

  async function reviewDraft(action: "validating" | "publishing") {
    if (!draft) return;
    setBusy(action);
    setError(null);
    try {
      if (action === "validating") {
        setDraft(await validateDraft(draft));
      } else {
        const published = await publishDraft(draft);
        setSnapshot({ case: published.case, bundle_id: published.bundle_id });
        setDraft(null);
        setMessage(published.applied ? `Published revision ${published.case.revision}.` : "No changes to publish.");
        await loadDrafts();
      }
    } catch (caught) {
      await handleError(caught);
    } finally {
      setBusy(null);
    }
  }

  const model = draft?.case ?? snapshot?.case;
  const stale = !!draft && draft.base_revision !== snapshot?.case.revision;
  const validated = !!draft?.validation && draft.validated_hash === draft.content_hash;
  const canPublish = validated && draft?.validation?.valid && !stale && !!draft?.changes.length;

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <p className="eyebrow">Structural mechanics</p>
          <h1>Kratos Semantic Authoring</h1>
        </div>
        <div className="app-header__status" aria-label="Case status">
          <Tag type="blue">Published revision {snapshot?.case.revision ?? "—"}</Tag>
          {draft && <Tag type="purple">Draft · from revision {draft.base_revision}</Tag>}
          <Tag type="gray">Units {model?.unit_system ?? "—"}</Tag>
        </div>
      </header>

      <main className="app-main">
        <Tabs>
          <TabList aria-label="Workspace sections" contained fullWidth>
            <Tab>Authoring</Tab>
            <Tab>Revisions</Tab>
          </TabList>
          <TabPanels>
            <TabPanel className="workspace-tab">
              <Grid fullWidth className="workspace">
                <Column sm={4} md={3} lg={4}>
                  <Tile className="authoring-panel">
                    <div>
                      <p className="eyebrow">Authoring</p>
                      <h2>Edit a draft</h2>
                      <p className="panel-intro">Describe a change, review it, then validate and publish. Prompts never change the published revision.</p>
                    </div>
                    <Select id="working-copy" labelText="Working copy" value={draft?.id ?? ""}
                      disabled={!snapshot || !!busy} onChange={(event) => void selectDraft(event.target.value)}>
                      <SelectItem value="" text={`New draft from revision ${snapshot?.case.revision ?? "—"}`} />
                      {drafts.map((item) => <SelectItem key={item.id} value={item.id}
                        text={`Draft ${item.id.slice(0, 8)} · from revision ${item.base_revision}`} />)}
                    </Select>
                    {stale && <InlineNotification kind="warning" lowContrast hideCloseButton title="Older base revision"
                      subtitle="This draft is preserved for review. Start a new draft from the published revision to make further changes." />}
                    <form onSubmit={handleSubmit}>
                      <Stack gap={5}>
                        <TextArea id="prompt" labelText="Prompt" helperText="Bare numbers use the case's current units."
                          placeholder="Change the load direction on the top surface to [0, 0, -1]."
                          value={prompt} maxLength={4000} rows={5} disabled={!model || !!busy || stale}
                          onChange={(event) => setPrompt(event.target.value)} />
                        <Button type="submit" disabled={!model || !prompt.trim() || !!busy || stale}>Propose changes</Button>
                      </Stack>
                    </form>
                    {busy && <InlineLoading description={{ editing: "Preparing draft", validating: "Validating draft", publishing: "Publishing revision", loading: "Loading draft" }[busy]} />}
                    {error && <InlineNotification kind="error" lowContrast hideCloseButton title="Request failed" subtitle={error} />}
                    {message && <section className="latest-response" aria-labelledby="response-title">
                      <h3 id="response-title">Latest response</h3><p>{message}</p>
                    </section>}
                    {draft && <section className="draft-review" aria-label="Draft actions">
                      <h3>Review and publish</h3>
                      <p className="panel-intro">{draft.changes.length} semantic changes · {draft.native_changes.length} file changes</p>
                      {validated && draft.validation && <Validation report={draft.validation} />}
                      {!validated && <p className="panel-intro">Validate this version of the draft before publishing.</p>}
                      <div className="revision-actions">
                        <Button kind="secondary" size="sm" disabled={!!busy || stale} onClick={() => void reviewDraft("validating")}>Validate</Button>
                        <Button size="sm" disabled={!!busy || !canPublish} onClick={() => void reviewDraft("publishing")}>Publish revision</Button>
                      </div>
                    </section>}
                  </Tile>
                </Column>

                <Column sm={4} md={5} lg={12} className="model-column">
                  <Tile className="model-panel">
                    <div className="model-panel__heading">
                      <div><p className="eyebrow">{draft ? "Draft preview" : "Published case"}</p><h2>Canonical model</h2></div>
                      {model && <div className="model-panel__counts">
                        <Tag type="blue">{Object.keys(model.materials).length} materials</Tag>
                        <Tag type="purple">{Object.keys(model.loads).length} loads</Tag>
                      </div>}
                    </div>
                    <Tabs>
                      <TabList aria-label="Model views" contained><Tab>Model</Tab><Tab>Changes</Tab><Tab>Technical</Tab></TabList>
                      <TabPanels>
                        <TabPanel className="model-view-tab"><div className="flow-frame">
                          {loading ? <div className="model-loading"><SkeletonText heading width="45%" /><SkeletonText paragraph lineCount={6} /></div>
                            : model ? <CanonicalFlow model={model} /> : <p className="model-empty">The canonical model is unavailable.</p>}
                        </div></TabPanel>
                        <TabPanel className="model-detail">
                          <h3>Semantic changes</h3>
                          {draft ? <><Changes changes={draft.changes} />
                            <details className="native-details"><summary>Compiled file changes ({draft.native_changes.length})</summary><Changes changes={draft.native_changes} /></details>
                          </> : <p className="panel-intro">Propose changes or open a saved draft to review its differences.</p>}
                        </TabPanel>
                        <TabPanel className="model-detail">
                          <h3>Coverage</h3>
                          <p className="panel-intro">Semantic components can be edited with tools. Native-only fields are retained without interpretation.</p>
                          {coverage && <>
                            <Validation report={coverage} />
                            <ul className="coverage-list">{coverage.coverage.map((entry, index) => (
                              <li key={`${entry.path}-${index}`}><code>{entry.path}</code><Tag type={entry.status === "semantic" ? "blue" : "gray"}>{entry.status}</Tag></li>
                            ))}</ul>
                          </>}
                          <details className="native-details"><summary>Canonical JSON</summary><pre className="json-view">{JSON.stringify(model, null, 2)}</pre></details>
                        </TabPanel>
                      </TabPanels>
                    </Tabs>
                  </Tile>
                </Column>
              </Grid>
            </TabPanel>
            <TabPanel className="workspace-tab"><RevisionPanel snapshot={snapshot} onRefresh={loadCurrentCase} /></TabPanel>
          </TabPanels>
        </Tabs>
      </main>
    </div>
  );
}
