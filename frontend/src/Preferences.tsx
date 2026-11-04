import { useId } from "react";
import { translate } from "./i18n";
import { Icon, type IconName } from "./ui";

interface Props {
  language: string; theme: string;
  onLanguage: (value: string) => void; onTheme: (value: string) => void;
  compact?: boolean;
}

export function Preferences({ language, theme, onLanguage, onTheme, compact = false }: Props) {
  const themeId = useId();
  const languageId = useId();
  const t = (key: string) => translate(language, key);
  const options: [string, IconName][] = [["light", "sun"], ["dark", "moon"], ["system", "assets"]];
  return <div className={compact ? "preferences is-compact" : "preferences"}>
    <fieldset className="preference-group" role="radiogroup" aria-label={t("theme")}>
      <legend>{t("theme")}</legend>
      <div className="segmented">{options.map(([value, icon]) => <label key={value} title={t(value)}>
        <input type="radio" name={themeId} value={value} checked={theme === value} onChange={() => onTheme(value)} />
        <span><Icon name={icon} />{!compact && t(value)}{compact && <span className="sr-only">{t(value)}</span>}</span>
      </label>)}</div>
    </fieldset>
    <fieldset className="preference-group" role="radiogroup" aria-label={t("language")}>
      <legend>{t("language")}</legend>
      <div className="segmented">{[["es", "Español", "ES"], ["en", "English", "EN"]].map(([value, name, short]) => <label key={value}>
        <input type="radio" name={languageId} aria-label={name} value={value} checked={language === value} onChange={() => onLanguage(value)} />
        <span>{short}</span>
      </label>)}</div>
    </fieldset>
  </div>;
}
