import React, { useEffect, useRef, useState } from "react";
import { request } from "./api";
import { translate } from "./i18n";
import Markdown from "react-markdown";

interface Message {
  role: "user" | "assistant";
  content: string;
  provider?: "Groq" | "Gemini";
}
interface Pending {
  messages: Message[];
  language: string;
}

export function ChatWidget({ language, onVisibilityChange }: { language: string; onVisibilityChange?: (open: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const inFlight = useRef(false);
  const launcher = useRef<HTMLButtonElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const log = useRef<HTMLUListElement>(null);
  const t = (key: string) => translate(language, key);
  const s = (es: string, en: string) => language === "en" ? en : es;

  useEffect(() => { if (open) field.current?.focus(); }, [open]);
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [messages, pending, busy, error, open]);

  function close() {
    setOpen(false);
    onVisibilityChange?.(false);
    launcher.current?.focus();
  }

  async function complete(payload: Pending) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true); setError(false); setPending(payload);
    try {
      let context = payload.messages.slice(-21);
      while (context.reduce((total, message) => total + message.content.length, 0) > 24000) context = context.slice(2);
      const result = await request<{ reply: string; provider: "Groq" | "Gemini" }>("/api/chat", "", {
        method: "POST",
        body: JSON.stringify({
          language: payload.language,
          messages: context.map(({ role, content }) => ({ role, content })),
        }),
      });
      setMessages([...payload.messages, { role: "assistant", content: result.reply, provider: result.provider }]);
      setPending(null); setInput("");
    } catch {
      setError(true);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  function send(value: string) {
    const content = value.trim();
    if (!content || inFlight.current) return;
    complete({ language, messages: [...messages, { role: "user", content }] });
  }

  return <>
    <button ref={launcher} type="button" className="chat-launcher" aria-controls="soc-chat-panel" aria-expanded={open}
      onClick={() => {
        if (open) close();
        else { setOpen(true); onVisibilityChange?.(true); }
      }}>
      <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-6 4V6a2 2 0 0 1 2-2Z" />
        <path d="M7 9h10M7 13h7" />
      </svg>
      {s("Asistente SOC", "SOC assistant")}
    </button>
    {open && <section id="soc-chat-panel" className="chat-widget" role="dialog" aria-modal="false" aria-labelledby="soc-chat-title"
      onKeyDown={event => { if (event.key === "Escape") close(); }}>
      <header className="chat-widget-header">
        <div><h2 id="soc-chat-title">{s("Asistente SOC", "SOC assistant")}</h2><p>{s("Groq · respaldo Gemini", "Groq · Gemini fallback")}</p></div>
        <button type="button" className="secondary" onClick={close} aria-label={s("Cerrar chat", "Close chat")}>×</button>
      </header>
      <ul ref={log} role="log" aria-live="polite" aria-label={t("chat")} className="chat-log">
        <li className="chat-assistant"><strong>{t("assistant")}</strong><p>{t("welcome")}</p></li>
        {messages.map((message, index) => <li className={message.role === "user" ? "chat-user" : "chat-assistant"} key={index}>
          <strong>{t(message.role === "user" ? "you" : "assistant")}</strong>
          {message.provider && <span className="chat-provider">{message.provider}{message.provider === "Gemini" ? s(" · respaldo", " · fallback") : ""}</span>}
          {message.role === "assistant"
            ? <div className="chat-markdown"><Markdown skipHtml components={{
                a: ({ children, href, title }) => href
                  ? <a href={href} title={title} target="_blank" rel="noopener noreferrer">{children}</a>
                  : <span>{children}</span>,
                img: ({ alt }) => <span>{alt}</span>,
              }}>{message.content}</Markdown></div>
            : <p>{message.content}</p>}
        </li>)}
        {pending && <li className="chat-user"><strong>{t("you")}</strong><p>{pending.messages.at(-1)!.content}</p></li>}
        {busy && <li className="chat-assistant"><p>{s("Preparando respuesta…", "Preparing a reply…")}</p></li>}
      </ul>
      {error && <div className="chat-error" role="alert">
        <p>{s("No se pudo obtener una respuesta. Puedes reintentar tu pregunta.", "A reply could not be retrieved. You can retry your question.")}</p>
        <button type="button" className="secondary" disabled={busy} onClick={() => pending && complete(pending)}>{s("Reintentar", "Retry")}</button>
      </div>}
      {!messages.length && !pending && <div className="suggestions">
        {["askReport", "askBoard", "askSla"].map(key => <button type="button" className="secondary" key={key} disabled={busy} onClick={() => send(t(key))}>{t(key)}</button>)}
      </div>}
      <form className="chat-compose" onSubmit={event => { event.preventDefault(); send(input); }}>
        <label htmlFor="chat-input">{t("chatLabel")}</label>
        <textarea ref={field} id="chat-input" value={input} onChange={event => setInput(event.target.value)}
          maxLength={1500} rows={2} required disabled={busy} placeholder={t("chatExample")}
          onKeyDown={event => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault(); send(input);
            }
          }} />
        <div className="chat-compose-footer"><p className="hint">{s("Tus mensajes se envían al proveedor de IA.", "Your messages are sent to the AI provider.")}</p><button disabled={busy || !input.trim()}>{t("send")}</button></div>
      </form>
    </section>}
  </>;
}
