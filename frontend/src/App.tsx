import { useEffect, useState, type FormEvent } from "react";
import {
  Button,
  Column,
  Grid,
  InlineLoading,
  InlineNotification,
  SkeletonText,
  Stack,
  Tag,
  TextArea,
  Tile,
} from "@carbon/react";

import { ApiError, editCase, getCase } from "./api";
import type { CaseSnapshot, EditResponse } from "./api";
import { CanonicalFlow } from "./CanonicalFlow";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error";
}

export default function App() {
  const [snapshot, setSnapshot] = useState<CaseSnapshot | null>(null);
  const [prompt, setPrompt] = useState("");
  const [result, setResult] = useState<EditResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  async function loadCurrentCase() {
    const current = await getCase();
    setSnapshot(current);
    return current;
  }

  useEffect(() => {
    loadCurrentCase()
      .catch((caught) => setError(errorMessage(caught)))
      .finally(() => setLoading(false));
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!snapshot || !prompt.trim()) return;

    setSubmitting(true);
    setError(null);

    try {
      const response = await editCase(prompt.trim(), snapshot.case.revision);
      setSnapshot({ case: response.case, bundle_id: response.bundle_id });
      setResult(response);
      if (response.applied) setPrompt("");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        await loadCurrentCase();
        setError("The case changed elsewhere. Review the refreshed model and retry.");
      } else {
        setError(errorMessage(caught));
      }
    } finally {
      setSubmitting(false);
    }
  }

  const model = snapshot?.case;

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <p className="eyebrow">Structural mechanics</p>
          <h1>Kratos Semantic Authoring</h1>
        </div>
        <div className="app-header__status" aria-label="Case status">
          <Tag type="blue">Revision {model?.revision ?? "—"}</Tag>
          <Tag type="gray">Units {model?.unit_system ?? "—"}</Tag>
        </div>
      </header>

      <Grid fullWidth className="workspace">
        <Column sm={4} md={3} lg={4}>
          <Tile className="authoring-panel">
            <div>
              <p className="eyebrow">Authoring</p>
              <h2>Edit the case</h2>
              <p className="panel-intro">
                Describe one change using the names shown in the canonical model.
              </p>
            </div>

            <form onSubmit={handleSubmit}>
              <Stack gap={5}>
                <TextArea
                  id="prompt"
                  labelText="Prompt"
                  helperText="Bare numbers use the case's current units."
                  placeholder="Set DENSITY for Frame.Core to 7850"
                  value={prompt}
                  maxLength={4000}
                  rows={5}
                  disabled={!model || submitting}
                  onChange={(event) => setPrompt(event.target.value)}
                />
                {submitting ? (
                  <InlineLoading description="Applying change" />
                ) : (
                  <Button type="submit" disabled={!model || !prompt.trim()}>
                    Apply change
                  </Button>
                )}
              </Stack>
            </form>

            {error && (
              <InlineNotification
                kind="error"
                lowContrast
                hideCloseButton
                title="Request failed"
                subtitle={error}
              />
            )}

            {result && (
              <section className="latest-response" aria-labelledby="response-title">
                <div className="latest-response__heading">
                  <h3 id="response-title">Latest response</h3>
                  <Tag type={result.applied ? "green" : "gray"}>
                    {result.applied ? "Applied" : "No change"}
                  </Tag>
                </div>
                <p>{result.message}</p>
                {result.changes.length > 0 && (
                  <ul className="change-list">
                    {result.changes.map((change) => (
                      <li key={change.field}>
                        <code>{change.field}</code>
                        <span>
                          {change.before.toLocaleString()} →{" "}
                          {change.after.toLocaleString()}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}
          </Tile>
        </Column>

        <Column sm={4} md={5} lg={12} className="model-column">
          <Tile className="model-panel">
            <div className="model-panel__heading">
              <div>
                <p className="eyebrow">Current revision</p>
                <h2>Canonical model</h2>
              </div>
              {model && (
                <div className="model-panel__counts">
                  <Tag type="blue">
                    {Object.keys(model.materials).length} materials
                  </Tag>
                  <Tag type="purple">
                    {Object.keys(model.processes).length} processes
                  </Tag>
                </div>
              )}
            </div>

            <div className="flow-frame">
              {loading ? (
                <div className="model-loading">
                  <SkeletonText heading width="45%" />
                  <SkeletonText paragraph lineCount={6} />
                </div>
              ) : model ? (
                <CanonicalFlow model={model} />
              ) : (
                <p className="model-empty">The canonical model is unavailable.</p>
              )}
            </div>
          </Tile>
        </Column>
      </Grid>
    </div>
  );
}
