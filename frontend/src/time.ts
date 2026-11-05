const peruTimeZone = "America/Lima";
const peruCalendar = new Intl.DateTimeFormat("en-CA", {
  timeZone: peruTimeZone, year: "numeric", month: "2-digit", day: "2-digit",
});

export function peruDateTime(value: string | Date | null, language: string, options?: Intl.DateTimeFormatOptions) {
  if (!value) return "—";
  const date = typeof value === "string" ? new Date(value) : value;
  return date.toLocaleString(language === "en" ? "en-US" : "es-PE", { ...options, timeZone: peruTimeZone });
}

export function peruDay(value: string) {
  const parts = Object.fromEntries(peruCalendar.formatToParts(new Date(value)).map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}
