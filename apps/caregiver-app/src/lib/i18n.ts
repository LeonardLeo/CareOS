/**
 * English and Spanish strings.
 *
 * `09_UX_Design_and_User_Flows.md` design principle 6 makes EN + ES a baseline for the
 * caregiver app rather than a later localization pass, and specifically warns against
 * hardcoded string concatenation. So every string is a whole sentence keyed by meaning, and
 * anything variable is interpolated by named token — never assembled from fragments, because
 * Spanish will not agree with English on word order, gender, or pluralization.
 *
 * The Spanish is not machine-translated placeholder text to be replaced later: it is the
 * shipping copy, and it is deliberately as short as the English so both fit the same layout
 * at the same touch-target size.
 */

export type Locale = "en" | "es";

const STRINGS = {
  en: {
    appName: "CareOS",
    appSubtitle: "Caregiver",

    signIn: "Sign in",
    email: "Email",
    password: "Password",
    signingIn: "Signing in…",
    signInFailed: "That email and password did not match. Please try again.",
    signInDisabled: "This account has been disabled. Contact your agency administrator.",
    signOut: "Sign out",

    today: "Today",
    noVisitsToday: "No visits scheduled for today.",
    scheduleFrom: "Schedule as of {time}",
    showingCached: "Showing your saved schedule. It will update when you are back online.",

    offline: "Offline",
    online: "Online",
    willSync: "Saved on this phone — will send when you have signal",
    syncing: "Sending…",
    synced: "Sent",
    needsHelp: "Could not send. Please call the office.",
    pendingCount: "{count} waiting to send",
    retryNow: "Try again now",

    clockIn: "Clock in",
    clockOut: "Clock out",
    clockedInAt: "Clocked in at {time}",
    clockedOutAt: "Clocked out at {time}",
    visitComplete: "Visit complete",
    clockingIn: "Clocking in…",
    clockingOut: "Clocking out…",

    tasks: "Authorized tasks",
    noTasks: "No tasks listed on the care plan.",
    address: "Address",
    noAddress: "No address on file — call the office.",
    getDirections: "Directions",

    locationOn: "Location recorded",
    locationOff: "No location — recorded as an exception",
    locationReason: "Reason: {reason}",
    locationExplainer:
      "Your clock-in is saved either way. The office will see why location was missing.",

    back: "Back",
    language: "Language",
  },
  es: {
    appName: "CareOS",
    appSubtitle: "Cuidador",

    signIn: "Iniciar sesión",
    email: "Correo electrónico",
    password: "Contraseña",
    signingIn: "Iniciando sesión…",
    signInFailed: "El correo y la contraseña no coinciden. Inténtelo de nuevo.",
    signInDisabled:
      "Esta cuenta ha sido desactivada. Comuníquese con el administrador de su agencia.",
    signOut: "Cerrar sesión",

    today: "Hoy",
    noVisitsToday: "No hay visitas programadas para hoy.",
    scheduleFrom: "Horario al {time}",
    showingCached: "Mostrando su horario guardado. Se actualizará cuando vuelva a tener señal.",

    offline: "Sin conexión",
    online: "Con conexión",
    willSync: "Guardado en este teléfono — se enviará cuando tenga señal",
    syncing: "Enviando…",
    synced: "Enviado",
    needsHelp: "No se pudo enviar. Llame a la oficina.",
    pendingCount: "{count} pendiente(s) de enviar",
    retryNow: "Intentar ahora",

    clockIn: "Registrar entrada",
    clockOut: "Registrar salida",
    clockedInAt: "Entrada registrada a las {time}",
    clockedOutAt: "Salida registrada a las {time}",
    visitComplete: "Visita completa",
    clockingIn: "Registrando entrada…",
    clockingOut: "Registrando salida…",

    tasks: "Tareas autorizadas",
    noTasks: "No hay tareas en el plan de cuidado.",
    address: "Dirección",
    noAddress: "No hay dirección registrada — llame a la oficina.",
    getDirections: "Indicaciones",

    locationOn: "Ubicación registrada",
    locationOff: "Sin ubicación — registrado como excepción",
    locationReason: "Motivo: {reason}",
    locationExplainer:
      "Su entrada se guarda de todas formas. La oficina verá por qué faltó la ubicación.",

    back: "Atrás",
    language: "Idioma",
  },
} as const;

export type StringKey = keyof (typeof STRINGS)["en"];

const LOCALE_KEY = "careos:locale";

export function detectLocale(): Locale {
  const stored = typeof localStorage !== "undefined" ? localStorage.getItem(LOCALE_KEY) : null;
  if (stored === "en" || stored === "es") return stored;
  const nav = typeof navigator !== "undefined" ? navigator.language : "en";
  return nav.toLowerCase().startsWith("es") ? "es" : "en";
}

export function storeLocale(locale: Locale): void {
  if (typeof localStorage !== "undefined") localStorage.setItem(LOCALE_KEY, locale);
}

/**
 * Look up a string, substituting `{named}` tokens.
 *
 * Interpolation is by name rather than position so a translation is free to reorder tokens,
 * which is the whole reason not to concatenate.
 */
export function translate(
  locale: Locale,
  key: StringKey,
  tokens: Record<string, string | number> = {},
): string {
  const template: string = STRINGS[locale][key] ?? STRINGS.en[key];
  return template.replace(/\{(\w+)\}/g, (match, token: string) =>
    token in tokens ? String(tokens[token]) : match,
  );
}

export type Translator = (key: StringKey, tokens?: Record<string, string | number>) => string;

export function translatorFor(locale: Locale): Translator {
  return (key, tokens) => translate(locale, key, tokens);
}

/** Every locale must define every key, or a caregiver hits English mid-sentence. */
export function missingKeys(): { locale: Locale; key: string }[] {
  const reference = Object.keys(STRINGS.en);
  const gaps: { locale: Locale; key: string }[] = [];
  for (const locale of ["en", "es"] as Locale[]) {
    const defined = new Set(Object.keys(STRINGS[locale]));
    for (const key of reference) {
      if (!defined.has(key)) gaps.push({ locale, key });
    }
  }
  return gaps;
}
