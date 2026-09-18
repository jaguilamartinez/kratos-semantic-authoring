import { useEffect, useRef, useState, type FormEvent } from "react";
import { ChevronLeft, ChevronRight, Maximize, Minimize } from "@carbon/icons-react";
import {
  Button, InlineLoading, InlineNotification, Select, SelectItem,
  SkeletonText, Stack, Tab, TabList, TabPanel, TabPanels, Tabs, Tag, TextArea, Tile,
} from "@carbon/react";

import {
  ApiError, editCase, getCase, getCoverage, getDraft, getDrafts,
  publishDraft, validateDraft,
} from "./api";
import type {
  CaseSnapshot, ChatMessage, Draft, ValidationReport,
} from "./api";
import { CanonicalFlow } from "./CanonicalFlow";
import { CanonicalJson } from "./CanonicalJson";
import { DraftChangeLog } from "./DraftChangeLog";
import { RevisionPanel } from "./RevisionPanel";

const ACTIVE_DRAFT_KEY = "ksa.active-draft";
const CHAT_PANEL_MODE_KEY = "ksa.chat-panel-mode";
const NO_MESSAGES: ChatMessage[] = [];
type ChatPanelMode = "collapsed" | "standard" | "expanded";

function rememberActiveDraft(id: string | null): void {
  if (id) window.localStorage.setItem(ACTIVE_DRAFT_KEY, id);
  else window.localStorage.removeItem(ACTIVE_DRAFT_KEY);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error";
}

function initialChatPanelMode(): ChatPanelMode {
  const saved = window.localStorage.getItem(CHAT_PANEL_MODE_KEY);
  return saved === "collapsed" || saved === "expanded" ? saved : "standard";
}

function DraftConversation({
  messages,
  pending,
  thinking,
}: {
  messages: ChatMessage[];
  pending: string | null;
  thinking: boolean;
}) {
  const log = useRef<HTMLOListElement>(null);
  const turns = messages.filter((message) => message.role === "user").length;

  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [messages.length, pending, thinking]);

  return (
    <section className="draft-conversation" aria-labelledby="conversation-title">
      <div className="draft-conversation__heading">
        <h3 id="conversation-title">Conversation</h3>
        <span>{turns} {turns === 1 ? "turn" : "turns"}</span>
      </div>
      <ol className="conversation-log" ref={log} role="log" aria-live="polite" aria-relevant="additions">
        {!messages.length && !pending && (
          <li className="conversation-log__empty">
            <strong>Start a conversation</strong>
            <span>Ask about the case or describe the first change you want to make.</span>
          </li>
        )}
        {messages.map((message, index) => (
          <li className={`conversation-message conversation-message--${message.role}`}
            key={`${message.role}-${index}`}>
            <span>{message.role === "user" ? "You" : "KSA"}</span>
            <p>{message.content}</p>
          </li>
        ))}
        {pending && (
          <li className="conversation-message conversation-message--user conversation-message--pending">
            <span>You</span><p>{pending}</p>
          </li>
        )}
        {thinking && (
          <li className="conversation-message conversation-message--assistant conversation-message--thinking">
            <span>KSA</span><InlineLoading description="Thinking" />
          </li>
        )}
      </ol>
    </section>
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
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"editing" | "validating" | "publishing" | "loading" | null>(null);
  const [chatPanelMode, setChatPanelMode] = useState<ChatPanelMode>(initialChatPanelMode);

  useEffect(() => {
    window.localStorage.setItem(CHAT_PANEL_MODE_KEY, chatPanelMode);
  }, [chatPanelMode]);

  async function loadCurrentCase() {
    const current = await getCase();
    setSnapshot(current);
    return current;
  }

  async function loadDrafts() {
    const response = await getDrafts();
    const openDrafts = response.drafts.filter((item) => item.status === "editing");
    setDrafts(openDrafts);
    return openDrafts;
  }

  useEffect(() => {
    async function loadWorkspace() {
      try {
        const [, openDrafts] = await Promise.all([loadCurrentCase(), loadDrafts()]);
        const activeId = window.localStorage.getItem(ACTIVE_DRAFT_KEY);
        const activeDraft = openDrafts.find((item) => item.id === activeId);
        if (activeDraft) setDraft(activeDraft);
        else if (activeId) rememberActiveDraft(null);
      } catch (caught) {
        setError(errorMessage(caught));
      } finally {
        setLoading(false);
      }
    }
    void loadWorkspace();
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
        draft ? getDraft(draft.id).then((current) => {
          setDraft(current);
          rememberActiveDraft(current.id);
        }) : Promise.resolve(),
      ]);
      setError("The case or draft changed elsewhere. Your draft is preserved; review the refreshed state before continuing.");
    } else {
      setError(errorMessage(caught));
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!snapshot || !prompt.trim()) return;
    const submittedPrompt = prompt.trim();
    setBusy("editing");
    setError(null);
    setNotice(null);
    setPrompt("");
    setPendingPrompt(submittedPrompt);
    try {
      const response = await editCase(
        submittedPrompt, draft?.base_revision ?? snapshot.case.revision, draft?.id, draft?.content_hash,
      );
      if (response.draft) {
        setDraft(response.draft);
        rememberActiveDraft(response.draft.id);
        await loadDrafts();
      }
    } catch (caught) {
      setPrompt((current) => current || submittedPrompt);
      await handleError(caught);
    } finally {
      setPendingPrompt(null);
      setBusy(null);
    }
  }

  async function selectDraft(id: string) {
    setError(null);
    setNotice(null);
    if (!id) {
      setDraft(null);
      rememberActiveDraft(null);
      return;
    }
    setBusy("loading");
    try {
      const selected = await getDraft(id);
      setDraft(selected);
      rememberActiveDraft(selected.id);
    }
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
        rememberActiveDraft(null);
        setNotice(published.applied ? `Published revision ${published.case.revision}.` : "No changes to publish.");
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
              <div className={`authoring-workspace authoring-workspace--${chatPanelMode}`}>
                {chatPanelMode === "collapsed" ? (
                  <aside className="chat-panel-rail" aria-label="Conversation panel">
                    <Button kind="ghost" size="sm" hasIconOnly renderIcon={ChevronRight}
                      iconDescription="Open chat" onClick={() => setChatPanelMode("standard")} />
                    <span aria-hidden="true">Chat</span>
                  </aside>
                ) : (
                  <aside className="chat-panel">
                  <Tile className="authoring-panel">
                    <div className="authoring-panel__header">
                      <div>
                        <p className="eyebrow">Authoring</p>
                        <h2>Draft conversation</h2>
                        <p className="panel-intro">Ask about the case or describe a change. This conversation remains attached to the draft.</p>
                      </div>
                      <div className="chat-panel__controls">
                        <Button kind="ghost" size="sm" hasIconOnly
                          renderIcon={chatPanelMode === "expanded" ? Minimize : Maximize}
                          iconDescription={chatPanelMode === "expanded" ? "Use standard chat width" : "Expand chat"}
                          onClick={() => setChatPanelMode(chatPanelMode === "expanded" ? "standard" : "expanded")} />
                        <Button kind="ghost" size="sm" hasIconOnly renderIcon={ChevronLeft}
                          iconDescription="Collapse chat" onClick={() => setChatPanelMode("collapsed")} />
                      </div>
                    </div>
                    <Select id="working-copy" labelText="Working copy" value={draft?.id ?? ""}
                      disabled={!snapshot || !!busy} onChange={(event) => void selectDraft(event.target.value)}>
                      <SelectItem value="" text={`New draft from revision ${snapshot?.case.revision ?? "—"}`} />
                      {drafts.map((item) => <SelectItem key={item.id} value={item.id}
                        text={`Draft ${item.id.slice(0, 8)} · from revision ${item.base_revision}`} />)}
                    </Select>
                    {notice && <InlineNotification kind="success" lowContrast hideCloseButton title={notice} />}
                    {stale && <InlineNotification kind="warning" lowContrast hideCloseButton title="Older base revision"
                      subtitle="This draft is preserved for review. Start a new draft from the published revision to make further changes." />}
                    <DraftConversation messages={draft?.messages ?? NO_MESSAGES}
                      pending={pendingPrompt} thinking={busy === "editing"} />
                    <form className="conversation-composer" onSubmit={handleSubmit}>
                      <Stack gap={5}>
                        <TextArea id="prompt" labelText="Message"
                          helperText="Enter to send · Shift+Enter for a new line · bare numbers use current case units."
                          placeholder="Ask about the case or describe a change."
                          value={prompt} maxLength={4000} rows={3} disabled={!model || !!busy || stale}
                          onChange={(event) => setPrompt(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" && !event.shiftKey) {
                              event.preventDefault();
                              event.currentTarget.form?.requestSubmit();
                            }
                          }} />
                        <Button type="submit" disabled={!model || !prompt.trim() || !!busy || stale}>Send</Button>
                      </Stack>
                    </form>
                    {busy && busy !== "editing" && <InlineLoading description={{
                      validating: "Validating draft", publishing: "Publishing revision", loading: "Loading draft",
                    }[busy]} />}
                    {error && <InlineNotification kind="error" lowContrast hideCloseButton title="Request failed" subtitle={error} />}
                    {draft && <section className="draft-review" aria-label="Draft actions">
                      <h3>Review and publish</h3>
                      <p className="panel-intro">{draft.changes.length} semantic changes · {draft.native_changes.length} file changes</p>
                      {validated && draft.validation && <Validation report={draft.validation} />}
                      {!draft.changes.length && <p className="panel-intro">No model changes yet.</p>}
                      {!!draft.changes.length && !validated && <p className="panel-intro">Validate this version of the draft before publishing.</p>}
                      <div className="revision-actions">
                        <Button kind="secondary" size="sm" disabled={!!busy || stale || !draft.changes.length}
                          onClick={() => void reviewDraft("validating")}>Validate</Button>
                        <Button size="sm" disabled={!!busy || !canPublish} onClick={() => void reviewDraft("publishing")}>Publish revision</Button>
                      </div>
                    </section>}
                  </Tile>
                  </aside>
                )}

                <section className="model-column">
                  <Tile className="model-panel">
                    <div className="model-panel__heading">
                      <div><p className="eyebrow">{draft ? "Draft preview" : "Published case"}</p><h2>Canonical model</h2></div>
                      {model && <div className="model-panel__counts">
                        <Tag type="blue">{Object.keys(model.materials).length} materials</Tag>
                        <Tag type="purple">{Object.keys(model.loads).length} loads</Tag>
                      </div>}
                    </div>
                    <Tabs>
                      <TabList aria-label="Model views" contained><Tab>Model</Tab><Tab>Technical</Tab><Tab>Changelog</Tab></TabList>
                      <TabPanels>
                        <TabPanel className="model-view-tab"><div className="flow-frame">
                          {loading ? <div className="model-loading"><SkeletonText heading width="45%" /><SkeletonText paragraph lineCount={6} /></div>
                            : model ? <CanonicalFlow model={model} baseline={draft ? snapshot?.case : undefined}
                              changes={draft?.changes} /> : <p className="model-empty">The canonical model is unavailable.</p>}
                        </div></TabPanel>
                        <TabPanel className="model-detail">
                          <h3>Canonical schema</h3>
                          <p className="panel-intro">Keys and values from the complete canonical model, including nested settings and native extensions.</p>
                          {draft && <p className="technical-diff-note">Proposed changes are shown as a red removal and a green addition.</p>}
                          {model ? <CanonicalJson model={model} baseline={draft ? snapshot?.case : undefined}
                            changes={draft?.changes} /> : <p className="model-empty">The canonical model is unavailable.</p>}
                          {coverage && <section className="technical-coverage">
                            <h3>Coverage</h3>
                            <Validation report={coverage} />
                            <ul className="coverage-list">{coverage.coverage.map((entry, index) => (
                              <li key={`${entry.path}-${index}`}><code>{entry.path}</code><Tag type={entry.status === "semantic" ? "blue" : "gray"}>{entry.status}</Tag></li>
                            ))}</ul>
                          </section>}
                        </TabPanel>
                        <TabPanel className="model-detail">
                          <h3>Draft changelog</h3>
                          <p className="panel-intro">Model updates made during this conversation, kept in order.</p>
                          {draft ? <DraftChangeLog entries={draft.change_log ?? []}
                            currentChanges={draft.changes} currentNativeChanges={draft.native_changes} />
                            : <p className="panel-intro">Start or open a draft to see its changelog.</p>}
                        </TabPanel>
                      </TabPanels>
                    </Tabs>
                  </Tile>
                </section>
              </div>
            </TabPanel>
            <TabPanel className="workspace-tab"><RevisionPanel snapshot={snapshot} onRefresh={loadCurrentCase} /></TabPanel>
          </TabPanels>
        </Tabs>
      </main>
    </div>
  );
}
