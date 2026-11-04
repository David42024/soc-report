import React, { useEffect, useRef, useState } from "react";
import { request } from "./api";
import { translate } from "./i18n";
import Markdown from "react-markdown";
import { Icon } from "./ui";

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
  const [mobile, setMobile] = useState(false);
  const inFlight = useRef(false);
  const launcher = useRef<HTMLButtonElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const log = useRef<HTMLUListElement>(null);
  const t = (key: string) => translate(language, key);
  const s = (es: string, en: string) => language === "en" ? en : es;

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(max-width: 46rem)");
    const update = () => setMobile(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => { if (open && !busy) field.current?.focus(); }, [open, busy]);
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [messages, pending, busy, error, open]);
  useEffect(() => {
    if (!field.current) return;
    field.current.style.height = "auto";
    field.current.style.height = Math.min(field.current.scrollHeight, 160) + "px";
  }, [input, open]);

  function close() {
    setOpen(false);
    onVisibilityChange?.(false);
    requestAnimationFrame(() => launcher.current?.focus());
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
      aria-label={s("Asistente SOC", "SOC assistant")} title={s("Asistente SOC", "SOC assistant")}
      onClick={() => {
        if (open) close();
        else { setOpen(true); onVisibilityChange?.(true); }
      }}>
      <Icon name="chat" />
    </button>
    {open && <section id="soc-chat-panel" className="chat-widget" role="dialog" aria-modal={mobile} aria-labelledby="soc-chat-title"
      onKeyDown={event => {
        if (event.key === "Escape") close();
        if (mobile && event.key === "Tab") {
          const controls = event.currentTarget.querySelectorAll<HTMLElement>("button:not(:disabled), textarea:not(:disabled), a[href]");
          const first = controls[0], last = controls[controls.length - 1];
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
          if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
        }
      }}>
      <header className="chat-widget-header">
        <span className="assistant-avatar" aria-hidden="true"><Icon name="chat" /></span>
        <div><h2 id="soc-chat-title">{s("Asistente SOC", "SOC assistant")}</h2><p>{s("Groq · respaldo Gemini", "Groq · Gemini fallback")}</p></div>
        <div className="chat-window-actions">
          <button type="button" className="ghost" onClick={close} aria-label={s("Minimizar chat", "Minimize chat")} title={s("Minimizar chat", "Minimize chat")}><Icon name="minimize" /></button>
          <button type="button" className="ghost" onClick={close} aria-label={s("Cerrar chat", "Close chat")} title={s("Cerrar chat", "Close chat")}><Icon name="close" /></button>
        </div>
      </header>
      <ul ref={log} role="log" aria-live="polite" aria-label={t("chat")} className="chat-log">
        <li className="chat-assistant">
          <span className="assistant-avatar" aria-hidden="true"><Icon name="chat" /></span>
          <div className="chat-bubble"><strong className="sr-only">{t("assistant")}</strong><p>{t("welcome")}</p>
            {!messages.length && !pending && <div className="suggestions">
              {["askReport", "askBoard", "askSla"].map(key => <button type="button" className="secondary" key={key} disabled={busy} onClick={() => send(t(key))}>{t(key)}</button>)}
            </div>}
          </div>
        </li>
        {messages.map((message, index) => <li className={message.role === "user" ? "chat-user" : "chat-assistant"} key={index}>
          {message.role === "assistant" && <span className="assistant-avatar" aria-hidden="true"><Icon name="chat" /></span>}
          <div className="chat-bubble"><strong className="sr-only">{t(message.role === "user" ? "you" : "assistant")}</strong>
          {message.role === "assistant"
            ? <div className="chat-markdown"><Markdown skipHtml components={{
                a: ({ children, href, title }) => href
                  ? <a href={href} title={title} target="_blank" rel="noopener noreferrer">{children}</a>
                  : <span>{children}</span>,
                img: ({ alt }) => <span>{alt}</span>,
              }}>{message.content}</Markdown></div>
            : <p>{message.content}</p>}
          {message.provider && <small className="chat-provider">{message.provider}{message.provider === "Gemini" ? s(" · respaldo", " · fallback") : ""}</small>}
          </div>
        </li>)}
        {pending && <li className="chat-user"><div className="chat-bubble"><strong className="sr-only">{t("you")}</strong><p>{pending.messages.at(-1)!.content}</p></div></li>}
        {busy && <li className="chat-assistant">
          <span className="assistant-avatar" aria-hidden="true"><Icon name="chat" /></span>
          <div className="chat-bubble typing" role="status"><span className="sr-only">{s("Preparando respuesta…", "Preparing a reply…")}</span>
            <span aria-hidden="true">●</span><span aria-hidden="true">●</span><span aria-hidden="true">●</span>
          </div>
        </li>}
      </ul>
      {error && <div className="chat-error" role="alert">
        <p>{s("No se pudo obtener una respuesta. Puedes reintentar tu pregunta.", "A reply could not be retrieved. You can retry your question.")}</p>
        <button type="button" className="secondary" disabled={busy} onClick={() => pending && complete(pending)}>{s("Reintentar", "Retry")}</button>
      </div>}
      <form className="chat-compose" onSubmit={event => { event.preventDefault(); send(input); }}>
        <div className="chat-input-wrap">
        <textarea ref={field} id="chat-input" value={input} onChange={event => setInput(event.target.value)}
          aria-label={t("chatLabel")} maxLength={1500} rows={1} required disabled={busy} placeholder={t("chatExample")}
          onKeyDown={event => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault(); send(input);
            }
          }} />
        <button aria-label={t("send")} title={t("send")} disabled={busy || !input.trim()}><Icon name="send" /></button>
        </div>
        <p className="hint chat-privacy">{s("Tus mensajes se envían al proveedor de IA.", "Your messages are sent to the AI provider.")}</p>
      </form>
    </section>}
  </>;
}
