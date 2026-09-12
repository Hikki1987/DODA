"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ApiError,
  clearWorkspaceAiPreference,
  createConversation,
  getWorkspaceAiPreference,
  listConversationMessages,
  listConversations,
  setWorkspaceAiPreference,
  streamConversationMessage,
  switchConversationProvider,
  AI_PROVIDERS,
  type AiPreferenceOut,
  type AiProvider,
  type ChatMode,
  type ConversationOut,
  type MessageOut,
} from "@/lib/api";
import { useSession } from "@/lib/useSession";

const CHAT_MODES: ChatMode[] = ["FAST", "STANDARD", "DEEP"];

export default function ChatPage() {
  const params = useParams<{ id: string }>();
  const workspaceId = params.id;
  const sessionId = useSession();

  const [conversations, setConversations] = useState<ConversationOut[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageOut[] | null>(null);
  const [composerText, setComposerText] = useState("");
  const [mode, setMode] = useState<ChatMode>("STANDARD");
  const [streamingText, setStreamingText] = useState<string | null>(null);
  const [pendingUserText, setPendingUserText] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [creatingConversation, setCreatingConversation] = useState(false);
  const [pinProvider, setPinProvider] = useState<AiProvider>("OPENAI");
  const [pinModel, setPinModel] = useState("");
  const [pinning, setPinning] = useState(false);
  const [workspacePreference, setWorkspacePreferenceState] = useState<AiPreferenceOut | null>(null);
  const [workspaceProviderChoice, setWorkspaceProviderChoice] = useState<AiProvider>("OPENAI");
  const [workspaceModelChoice, setWorkspaceModelChoice] = useState("");
  const [savingWorkspacePreference, setSavingWorkspacePreference] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const selected = conversations?.find((c) => c.id === selectedId) ?? null;

  const refreshConversations = useCallback(() => {
    if (sessionId === null) return;
    listConversations(sessionId, workspaceId)
      .then((list) => {
        setConversations(list);
        setSelectedId((current) => current ?? list[0]?.id ?? null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Suhbatlarni yuklab bo'lmadi."));
  }, [sessionId, workspaceId]);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations]);

  useEffect(() => {
    if (sessionId === null) return;
    getWorkspaceAiPreference(sessionId, workspaceId).then(setWorkspacePreferenceState).catch(() => {});
  }, [sessionId, workspaceId]);

  const refreshMessages = useCallback(() => {
    if (sessionId === null || selectedId === null) return;
    listConversationMessages(sessionId, workspaceId, selectedId)
      .then(setMessages)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Xabarlarni yuklab bo'lmadi."));
  }, [sessionId, workspaceId, selectedId]);

  useEffect(() => {
    refreshMessages();
  }, [refreshMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText, pendingUserText]);

  async function handleNewConversation() {
    if (sessionId === null || creatingConversation) return;
    setCreatingConversation(true);
    try {
      const conversation = await createConversation(sessionId, workspaceId);
      setConversations((prev) => [conversation, ...(prev ?? [])]);
      setSelectedId(conversation.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Suhbat yaratib bo'lmadi.");
    } finally {
      setCreatingConversation(false);
    }
  }

  async function handlePinProvider(event: FormEvent) {
    event.preventDefault();
    if (sessionId === null || selectedId === null || pinning) return;
    setPinning(true);
    try {
      const updated = await switchConversationProvider(
        sessionId,
        workspaceId,
        selectedId,
        pinProvider,
        pinModel.trim().length > 0 ? pinModel.trim() : null,
      );
      setConversations((prev) => prev?.map((c) => (c.id === updated.id ? updated : c)) ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Provayderni o'rnatib bo'lmadi.");
    } finally {
      setPinning(false);
    }
  }

  async function handleSetWorkspacePreference(event: FormEvent) {
    event.preventDefault();
    if (sessionId === null || savingWorkspacePreference) return;
    setSavingWorkspacePreference(true);
    try {
      const updated = await setWorkspaceAiPreference(
        sessionId,
        workspaceId,
        workspaceProviderChoice,
        workspaceModelChoice.trim().length > 0 ? workspaceModelChoice.trim() : null,
      );
      setWorkspacePreferenceState(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Workspace AI afzalligini saqlab bo'lmadi.");
    } finally {
      setSavingWorkspacePreference(false);
    }
  }

  async function handleClearWorkspacePreference() {
    if (sessionId === null || savingWorkspacePreference) return;
    setSavingWorkspacePreference(true);
    try {
      await clearWorkspaceAiPreference(sessionId, workspaceId);
      setWorkspacePreferenceState({ provider: null, model: null });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Workspace AI afzalligini tozalab bo'lmadi.");
    } finally {
      setSavingWorkspacePreference(false);
    }
  }

  async function handleSend(event: FormEvent) {
    event.preventDefault();
    if (sessionId === null || selectedId === null || sending || composerText.trim().length === 0) return;
    const content = composerText.trim();
    setComposerText("");
    setPendingUserText(content);
    setStreamingText("");
    setSending(true);
    setError(null);
    try {
      for await (const chunk of streamConversationMessage(sessionId, workspaceId, selectedId, content, mode)) {
        if (chunk.kind === "text" || chunk.kind === "tool_status") {
          setStreamingText((prev) => (prev ?? "") + chunk.text);
        } else if (chunk.kind === "error") {
          setError(chunk.message);
        }
        // "done" carries the persisted final message, but the simplest,
        // least-duplicative source of truth is re-fetching the real list
        // below once the stream ends — same pattern as every other page's
        // refresh() after a mutation, rather than hand-reconciling state.
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Suhbat davomida xato yuz berdi.");
    } finally {
      setSending(false);
      setPendingUserText(null);
      setStreamingText(null);
      refreshMessages();
    }
  }

  if (sessionId === null) return null;

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <Link href={`/workspaces/${workspaceId}`} className="text-sm text-gray-500 hover:text-black">
          &larr; Workspace
        </Link>
        <h1 className="text-lg font-semibold">Chat</h1>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {workspacePreference !== null && (
        <form onSubmit={handleSetWorkspacePreference} className="flex items-center gap-2 text-xs">
          <span className="text-gray-500">
            Workspace standart AI ({workspacePreference.provider ?? "tizim standart"}
            {workspacePreference.model ? ` / ${workspacePreference.model}` : ""}):
          </span>
          <select
            aria-label="Workspace AI provayderi"
            value={workspaceProviderChoice}
            onChange={(event) => setWorkspaceProviderChoice(event.target.value as AiProvider)}
            className="rounded border border-gray-200 bg-gray-50 px-1 py-1"
          >
            {AI_PROVIDERS.map((provider) => (
              <option key={provider} value={provider}>
                {provider}
              </option>
            ))}
          </select>
          <input
            type="text"
            value={workspaceModelChoice}
            onChange={(event) => setWorkspaceModelChoice(event.target.value)}
            placeholder="model (ixtiyoriy)"
            className="w-32 rounded border border-gray-200 px-1 py-1"
          />
          <button
            type="submit"
            disabled={savingWorkspacePreference}
            className="rounded border border-gray-300 px-2 py-1 font-medium text-gray-700 disabled:opacity-50"
          >
            Saqlash
          </button>
          {workspacePreference.provider !== null && (
            <button
              type="button"
              onClick={handleClearWorkspacePreference}
              disabled={savingWorkspacePreference}
              className="text-red-600 hover:underline disabled:opacity-50"
            >
              Tizim standartga qaytarish
            </button>
          )}
        </form>
      )}

      <div className="flex gap-6">
        <aside className="w-48 shrink-0 space-y-2">
          <button
            onClick={handleNewConversation}
            disabled={creatingConversation}
            className="w-full rounded-md bg-black px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Yangi suhbat
          </button>
          <ul className="space-y-1">
            {conversations?.map((conversation) => (
              <li key={conversation.id}>
                <button
                  onClick={() => setSelectedId(conversation.id)}
                  className={`w-full truncate rounded-md px-2 py-1.5 text-left text-sm ${
                    conversation.id === selectedId ? "bg-gray-100 font-medium" : "text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  {conversation.title ?? "Suhbat"}
                </button>
              </li>
            ))}
            {conversations !== null && conversations.length === 0 && (
              <li className="text-xs text-gray-500">Hali suhbat yo&apos;q.</li>
            )}
          </ul>
        </aside>

        <section className="flex flex-1 flex-col gap-4">
          {selected === null ? (
            <p className="text-sm text-gray-500">Suhbat tanlang yoki yangisini yarating.</p>
          ) : (
            <>
              <form onSubmit={handlePinProvider} className="flex items-center gap-2 text-xs">
                <span className="text-gray-500">Provayder:</span>
                <select
                  aria-label="Suhbat provayderi"
                  value={pinProvider}
                  onChange={(event) => setPinProvider(event.target.value as AiProvider)}
                  className="rounded border border-gray-200 bg-gray-50 px-1 py-1"
                >
                  {AI_PROVIDERS.map((provider) => (
                    <option key={provider} value={provider}>
                      {provider}
                    </option>
                  ))}
                </select>
                <input
                  type="text"
                  value={pinModel}
                  onChange={(event) => setPinModel(event.target.value)}
                  placeholder="model (ixtiyoriy)"
                  className="w-36 rounded border border-gray-200 px-1 py-1"
                />
                <button
                  type="submit"
                  disabled={pinning}
                  className="rounded border border-gray-300 px-2 py-1 font-medium text-gray-700 disabled:opacity-50"
                >
                  Pin qilish
                </button>
                <span className="text-gray-400">
                  {selected.pinned_provider
                    ? `hozirgi: ${selected.pinned_provider}${selected.pinned_model ? " / " + selected.pinned_model : ""}`
                    : "hozirgi: tizim standart"}
                </span>
              </form>

              <div className="flex-1 space-y-3 overflow-y-auto rounded-md border border-gray-200 p-4">
                {messages?.map((message) => (
                  <div
                    key={message.id}
                    className={message.role === "USER" ? "text-right" : "text-left"}
                  >
                    <div
                      className={`inline-block max-w-[80%] rounded-md px-3 py-2 text-sm ${
                        message.role === "USER"
                          ? "bg-black text-white"
                          : message.role === "TOOL"
                            ? "bg-gray-50 text-gray-500 italic"
                            : "bg-gray-100 text-gray-900"
                      }`}
                    >
                      {message.content}
                      {message.role === "ASSISTANT" && message.provider && (
                        <div className="mt-1 text-xs text-gray-400">
                          {message.provider}
                          {message.model ? ` / ${message.model}` : ""}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                {pendingUserText !== null && (
                  <div className="text-right">
                    <div className="inline-block max-w-[80%] rounded-md bg-black px-3 py-2 text-sm text-white">
                      {pendingUserText}
                    </div>
                  </div>
                )}
                {streamingText !== null && (
                  <div className="text-left">
                    <div className="inline-block max-w-[80%] rounded-md bg-gray-100 px-3 py-2 text-sm text-gray-900">
                      {streamingText.length > 0 ? streamingText : "..."}
                    </div>
                  </div>
                )}
                {messages !== null && messages.length === 0 && pendingUserText === null && (
                  <p className="text-sm text-gray-500">Hali xabar yo&apos;q. Suhbatni boshlang.</p>
                )}
                <div ref={bottomRef} />
              </div>

              <form onSubmit={handleSend} className="flex gap-2">
                <select
                  aria-label="Chat rejimi"
                  value={mode}
                  onChange={(event) => setMode(event.target.value as ChatMode)}
                  className="rounded-md border border-gray-300 px-2 py-2 text-sm"
                  disabled={sending}
                >
                  {CHAT_MODES.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
                <input
                  type="text"
                  value={composerText}
                  onChange={(event) => setComposerText(event.target.value)}
                  placeholder="Xabar yozing..."
                  disabled={sending}
                  className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-black focus:outline-none disabled:opacity-50"
                />
                <button
                  type="submit"
                  disabled={sending || composerText.trim().length === 0}
                  className="rounded-md bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                >
                  {sending ? "..." : "Yuborish"}
                </button>
              </form>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
