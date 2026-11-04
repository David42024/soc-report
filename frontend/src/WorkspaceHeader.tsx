import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { request, type User } from "./api";
import { translate } from "./i18n";
import { Preferences } from "./Preferences";
import { Avatar, Icon, Popover, type IconName } from "./ui";

interface Props {
  title: string; icon: IconName; user: User; roleLabel: string; token: string;
  language: string; theme: string; signingOut: boolean; activeModule: string; noticeVersion: number;
  onLanguage: (value: string) => void; onTheme: (value: string) => void;
  onProfile: () => void; onLogout: () => void; onNotifications: () => void; onMenu: () => void; menuOpen: boolean;
  menuButtonRef: RefObject<HTMLButtonElement>;
}

export function WorkspaceHeader(props: Props) {
  const { title, icon, user, roleLabel, token, language, theme, signingOut, activeModule, noticeVersion } = props;
  const [popup, setPopup] = useState<"user" | "theme" | null>(null);
  const [unread, setUnread] = useState<number | null>(null);
  const userButton = useRef<HTMLButtonElement>(null);
  const themeButton = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => setPopup(null), []);
  const s = (es: string, en: string) => language === "es" ? es : en;
  const canRead = user.role !== "auditor";

  useEffect(() => {
    if (!canRead) return;
    let active = true;
    async function load() {
      try {
        const notices = await request<{ read_at: string | null }[]>("/api/notificaciones?limit=500", token);
        if (active) setUnread(notices.filter(item => !item.read_at).length);
      } catch { if (active) setUnread(null); }
    }
    void load();
    const interval = window.setInterval(load, 60_000);
    return () => { active = false; window.clearInterval(interval); };
  }, [token, canRead, activeModule, noticeVersion]);
  useEffect(close, [activeModule, close]);

  return <header className="page-bar">
    <button ref={props.menuButtonRef} type="button" className="ghost mobile-menu" aria-label={s("Menú", "Menu")} aria-controls="sidebar-menu"
      aria-expanded={props.menuOpen} onClick={props.onMenu}><Icon name="menu" /></button>
    <div className="page-title"><Icon name={icon} /><h1 id="module-title">{title}</h1></div>
    <div className="header-actions">
      {canRead && <button type="button" className="ghost notification-button" aria-label={s("Notificaciones", "Notifications") + (unread === null ? "" : ` · ${unread} ${s("sin leer", "unread")}`)}
        title={s("Notificaciones", "Notifications")} onClick={props.onNotifications}>
        <Icon name="bell" />{unread !== null && unread > 0 && <span className="unread-count">{unread >= 500 ? "500+" : unread}</span>}
      </button>}
      <div className="popover-anchor quick-theme">
        <button ref={themeButton} type="button" className="ghost" aria-label={s("Cambiar tema", "Change theme")}
          title={translate(language, theme)} aria-haspopup="dialog" aria-controls="theme-popover" aria-expanded={popup === "theme"}
          onClick={() => setPopup(popup === "theme" ? null : "theme")}><Icon name={theme === "dark" ? "moon" : theme === "light" ? "sun" : "assets"} /></button>
        {popup === "theme" && <Popover id="theme-popover" label={translate(language, "theme")} anchor={themeButton} onClose={close}>
          <Preferences language={language} theme={theme} onLanguage={props.onLanguage} onTheme={props.onTheme} />
        </Popover>}
      </div>
      <div className="popover-anchor">
        <button ref={userButton} type="button" className="ghost avatar-button" aria-label={s("Menú de usuario", "User menu")}
          title={user.username} aria-haspopup="dialog" aria-controls="user-popover" aria-expanded={popup === "user"}
          onClick={() => setPopup(popup === "user" ? null : "user")}><Avatar name={user.username} /></button>
        {popup === "user" && <Popover id="user-popover" label={s("Tu cuenta", "Your account")} anchor={userButton} onClose={close}>
          <div className="account-card"><Avatar name={user.username} /><div><strong>{user.username}</strong><p>{roleLabel}</p></div></div>
          <button type="button" className="ghost account-action" onClick={() => { close(); props.onProfile(); }}><Icon name="user" />{s("Mi perfil", "My profile")}</button>
          <Preferences language={language} theme={theme} onLanguage={props.onLanguage} onTheme={props.onTheme} />
          <button type="button" className="ghost sign-out" disabled={signingOut} onClick={props.onLogout}><Icon name="logout" />
            {signingOut ? s("Cerrando sesión…", "Signing out…") : s("Cerrar sesión", "Sign out")}
          </button>
        </Popover>}
      </div>
    </div>
  </header>;
}
