/**
 * English and Spanish strings for the admin app.
 *
 * `02_Product_Requirements_Document.md` requires English and Spanish at MVP, and
 * `09_UX_Design_and_User_Flows.md` design principle 6 warns specifically against hardcoded
 * string concatenation. So every entry is a whole sentence keyed by meaning, and anything
 * variable is interpolated by named token — never assembled from fragments, because Spanish
 * will not agree with English on word order, gender, or pluralization.
 *
 * The same shape as the caregiver app's `i18n.ts` on purpose. Two apps with two different
 * translation idioms is how one of them stops being maintained.
 *
 * **The Spanish here is shipping copy, not placeholder.** A dictionary half-filled with
 * English strings marked "TODO" renders as an app that switches language mid-screen, which is
 * worse than one that only speaks English — `missingKeys()` and the test over it exist so
 * that state cannot be reached quietly.
 *
 * Scheduling and compliance vocabulary is chosen for a US home-care agency whose bilingual
 * staff are usually speakers of Latin American Spanish, so "horario" rather than "agenda" for
 * a work schedule, and "cuidador" rather than "cuidadora" as the neutral job title used in
 * the caregiver app already.
 */

export type Locale = "en" | "es";

export const LOCALES: readonly Locale[] = ["en", "es"] as const;

export const LOCALE_LABEL: Record<Locale, string> = {
  // Each in its own language: someone looking for Spanish is looking for the word "Español",
  // not for "Spanish" written in a language they are trying to leave.
  en: "English",
  es: "Español",
};

const EN = {
    appName: "CareOS",
    appSubtitle: "Agency admin",

    // --- Navigation and shell
    navDashboard: "Dashboard",
    navScheduling: "Scheduling",
    navClients: "Clients",
    navExceptions: "Exceptions",
    navRecruiting: "Recruiting",
    navCredentialing: "Credentialing",
    navCompliance: "Compliance",
    navUsers: "Users",
    navMain: "Main",
    signOut: "Sign out",
    language: "Language",
    changeLanguage: "Change language",

    // --- Roles
    roleOwnerAdmin: "Owner / Admin",
    roleScheduler: "Scheduler",
    roleClinicalSupervisor: "Clinical Supervisor",
    roleCaregiver: "Caregiver",
    roleBillingRcm: "Billing / RCM",
    roleAuditor: "Auditor",

    // --- Sign in
    signIn: "Sign in",
    signInTitle: "Sign in to CareOS",
    email: "Email",
    password: "Password",
    signingIn: "Signing in…",
    signInFailed: "That email and password did not match. Please try again.",
    mfaNotice:
      "Multi-factor authentication is required for owner, clinical supervisor and billing roles before production use.",

    // --- Dashboard
    dashboardTitle: "Dashboard",
    coverageTitle: "Coverage",
    coverageCaption: "Assigned visits as a share of scheduled visits",
    openExceptions: "Open exceptions",
    unfilledVisits: "Unfilled visits",
    expiringCredentials: "Expiring credentials",
    activeCaregivers: "Active caregivers",
    last30Days: "Last 30 days",


    // --- Dashboard
    dashboardSubtitle: "Operational health across your agency.",
    needsAttention: "Needs attention",
    nothingNeedsAction: "Nothing needs action today",
    itemsNeedAction: "items need action",
    allClearDetail:
      "Every shift is covered, no credential has lapsed, and every caregiver is screened.",
    countUnfilled: "{count} unfilled",
    countExpiredCredential_one: "{count} expired credential",
    countExpiredCredential_other: "{count} expired credentials",
    countUnscreened: "{count} unscreened",
    coverageSubtitle: "Upcoming visits with a caregiver assigned",
    shiftsCovered: "Shifts covered",
    shiftsCoveredCaption:
      "A visit without a caregiver at its start time becomes a missed visit — and, for Medicaid clients, an EVV compliance exception.",
    caregiversCleared: "Caregivers cleared to work",
    caregiversClearedCaption:
      "Only caregivers with a cleared OIG/GSA exclusion check may be scheduled for publicly-funded visits.",
    scheduledVisits: "Scheduled visits",
    last14DaysPlotted: "Last 14 days plotted",
    expiringIn60Days: "Expiring in 60 days",
    unfilledNext72h: "Unfilled, next 72h",
    shiftsNeedingCaregiver: "Shifts needing a caregiver",
    next72SoonestFirst: "Next 72 hours, soonest first",
    openBoard: "Open board",
    everyShiftAssigned: "Every upcoming shift is assigned",
    nothingNext72: "Nothing needs attention in the next 72 hours.",
    unfilledNext72Caption: "Unfilled shifts, next 72 hours",
    credentialsNeedingRenewal: "Credentials needing renewal",
    expiredBlockAssignment: "Expired credentials block assignment immediately",
    viewAll: "View all",
    noCredentialsExpiring60: "No credentials expiring in the next 60 days",
    credentialsExpiring60Caption: "Credentials expiring within 60 days",
    colWhen: "When",
    colService: "Service",
    colCaregiver: "Caregiver",
    colCredential: "Credential",
    colExpires: "Expires",
    colStatus: "Status",
    noServiceCode: "No code",
    fill: "Fill",
    daysCount: "{count} days",
    sevenDays: "7 days",
    couldNotLoadDashboard: "Could not load the dashboard.",
    checkApiReachable: "Check that the CareOS API is running and reachable at CAREOS_API_URL.",

    // --- Scheduling
    schedulingTitle: "Scheduling",
    gapQueue: "Unfilled visits",
    noGaps: "Every scheduled visit has a caregiver assigned.",
    suggestedCaregivers: "Suggested caregivers",
    assign: "Assign",
    assigning: "Assigning…",
    assigned: "Assigned",
    whyThisSuggestion: "Why this caregiver",
    matchScore: "Match score",
    timeline: "Schedule",
    unassigned: "Unassigned",

    // --- Clients
    clientsTitle: "Clients",
    newClient: "New client",
    createClient: "Create client",
    creating: "Creating…",
    clientName: "Legal name",
    clientDob: "Date of birth",
    clientAddress: "Address",
    serviceState: "Service state",
    payerType: "Payer type",
    carePlans: "Care plans",
    noCarePlans: "No care plan yet. A visit cannot be scheduled without one.",
    authorizedTasks: "Authorized tasks",
    generateVisits: "Generate visits",
    noClients: "No clients yet.",

    // --- Exceptions
    exceptionsTitle: "Compliance exceptions",
    noExceptions: "No open exceptions.",
    resolve: "Resolve",
    resolving: "Resolving…",
    resolution: "How was this resolved?",
    raisedOn: "Raised {date}",
    severity: "Severity",

    // --- Recruiting
    recruitingTitle: "Recruiting",
    funnel: "Applicant funnel",
    applicants: "Applicants",
    stage: "Stage",
    noApplicants: "No applicants yet.",

    // --- Credentialing
    credentialingTitle: "Credentialing",
    expiringSoon: "Expiring soon",
    within7Days: "Within 7 days",
    within30Days: "Within 30 days",
    within60Days: "Within 60 days",
    expired: "Expired",
    noExpiring: "No credentials are expiring in the next 60 days.",

    // --- Compliance
    complianceTitle: "Compliance reviews",
    reviewType: "Review",
    lastPerformed: "Last performed",
    nextDue: "Next due",
    overdue: "Overdue",
    neverPerformed: "Never performed",

    // --- Users
    usersTitle: "Users",
    inviteUser: "Invite user",
    inviting: "Inviting…",
    role: "Role",
    changeRole: "Change role",
    endSessions: "End all sessions",
    endSessionsPrompt: "Why are you ending this user's sessions?",
    endingSessions: "Ending sessions…",
    initialPassword: "Initial password",
    fullName: "Full name",

    // --- Shared
    loading: "Loading…",
    none: "None",
    save: "Save",
    cancel: "Cancel",
    back: "Back",
    somethingWentWrong: "Something went wrong. Please try again.",
} as const;

export type StringKey = keyof typeof EN;

/**
 * Spanish, typed as `Record<StringKey, string>`.
 *
 * That annotation is the guard: a key added to `EN` and forgotten here is a **compile error**,
 * not something a reviewer has to notice or a runtime check has to catch after the fact. It is
 * the same idea as the API refusing to boot when a route has no access declaration — the
 * failure lands at the moment the mistake is made, and CI already runs `tsc`.
 */
const ES: Record<StringKey, string> = {
    appName: "CareOS",
    appSubtitle: "Administración de agencia",

    navDashboard: "Panel",
    navScheduling: "Horarios",
    navClients: "Clientes",
    navExceptions: "Excepciones",
    navRecruiting: "Contratación",
    navCredentialing: "Credenciales",
    navCompliance: "Cumplimiento",
    navUsers: "Usuarios",
    navMain: "Principal",
    signOut: "Cerrar sesión",
    language: "Idioma",
    changeLanguage: "Cambiar idioma",

    roleOwnerAdmin: "Propietario / Administrador",
    roleScheduler: "Coordinador de horarios",
    roleClinicalSupervisor: "Supervisor clínico",
    roleCaregiver: "Cuidador",
    roleBillingRcm: "Facturación / RCM",
    roleAuditor: "Auditor",

    signIn: "Iniciar sesión",
    signInTitle: "Iniciar sesión en CareOS",
    email: "Correo electrónico",
    password: "Contraseña",
    signingIn: "Iniciando sesión…",
    signInFailed: "El correo y la contraseña no coinciden. Inténtelo de nuevo.",
    mfaNotice:
      "La autenticación de múltiples factores es obligatoria para las funciones de propietario, supervisor clínico y facturación antes del uso en producción.",

    dashboardTitle: "Panel",
    coverageTitle: "Cobertura",
    coverageCaption: "Visitas asignadas como proporción de las programadas",
    openExceptions: "Excepciones abiertas",
    unfilledVisits: "Visitas sin cubrir",
    expiringCredentials: "Credenciales por vencer",
    activeCaregivers: "Cuidadores activos",
    last30Days: "Últimos 30 días",


    dashboardSubtitle: "Estado operativo de su agencia.",
    needsAttention: "Requiere atención",
    nothingNeedsAction: "Nada requiere acción hoy",
    itemsNeedAction: "elementos requieren acción",
    allClearDetail:
      "Todos los turnos están cubiertos, ninguna credencial ha vencido y todos los cuidadores están verificados.",
    countUnfilled: "{count} sin cubrir",
    countExpiredCredential_one: "{count} credencial vencida",
    countExpiredCredential_other: "{count} credenciales vencidas",
    countUnscreened: "{count} sin verificar",
    coverageSubtitle: "Próximas visitas con cuidador asignado",
    shiftsCovered: "Turnos cubiertos",
    shiftsCoveredCaption:
      "Una visita sin cuidador a su hora de inicio se convierte en una visita perdida y, para clientes de Medicaid, en una excepción de cumplimiento de EVV.",
    caregiversCleared: "Cuidadores habilitados para trabajar",
    caregiversClearedCaption:
      "Solo los cuidadores con verificación de exclusión OIG/GSA aprobada pueden asignarse a visitas con fondos públicos.",
    scheduledVisits: "Visitas programadas",
    last14DaysPlotted: "Últimos 14 días",
    expiringIn60Days: "Vencen en 60 días",
    unfilledNext72h: "Sin cubrir, próximas 72 h",
    shiftsNeedingCaregiver: "Turnos que necesitan cuidador",
    next72SoonestFirst: "Próximas 72 horas, las más cercanas primero",
    openBoard: "Abrir tablero",
    everyShiftAssigned: "Todos los turnos próximos están asignados",
    nothingNext72: "Nada requiere atención en las próximas 72 horas.",
    unfilledNext72Caption: "Turnos sin cubrir, próximas 72 horas",
    credentialsNeedingRenewal: "Credenciales que requieren renovación",
    expiredBlockAssignment: "Las credenciales vencidas impiden la asignación de inmediato",
    viewAll: "Ver todas",
    noCredentialsExpiring60: "No hay credenciales por vencer en los próximos 60 días",
    credentialsExpiring60Caption: "Credenciales que vencen en 60 días",
    colWhen: "Cuándo",
    colService: "Servicio",
    colCaregiver: "Cuidador",
    colCredential: "Credencial",
    colExpires: "Vence",
    colStatus: "Estado",
    noServiceCode: "Sin código",
    fill: "Cubrir",
    daysCount: "{count} días",
    sevenDays: "7 días",
    couldNotLoadDashboard: "No se pudo cargar el panel.",
    checkApiReachable: "Verifique que la API de CareOS esté en ejecución y accesible en CAREOS_API_URL.",

    schedulingTitle: "Horarios",
    gapQueue: "Visitas sin cubrir",
    noGaps: "Todas las visitas programadas tienen cuidador asignado.",
    suggestedCaregivers: "Cuidadores sugeridos",
    assign: "Asignar",
    assigning: "Asignando…",
    assigned: "Asignado",
    whyThisSuggestion: "Por qué este cuidador",
    matchScore: "Puntuación de coincidencia",
    timeline: "Horario",
    unassigned: "Sin asignar",

    clientsTitle: "Clientes",
    newClient: "Nuevo cliente",
    createClient: "Crear cliente",
    creating: "Creando…",
    clientName: "Nombre legal",
    clientDob: "Fecha de nacimiento",
    clientAddress: "Dirección",
    serviceState: "Estado de servicio",
    payerType: "Tipo de pagador",
    carePlans: "Planes de cuidado",
    noCarePlans: "Aún no hay plan de cuidado. No se puede programar una visita sin uno.",
    authorizedTasks: "Tareas autorizadas",
    generateVisits: "Generar visitas",
    noClients: "Aún no hay clientes.",

    exceptionsTitle: "Excepciones de cumplimiento",
    noExceptions: "No hay excepciones abiertas.",
    resolve: "Resolver",
    resolving: "Resolviendo…",
    resolution: "¿Cómo se resolvió?",
    raisedOn: "Registrada el {date}",
    severity: "Gravedad",

    recruitingTitle: "Contratación",
    funnel: "Embudo de solicitantes",
    applicants: "Solicitantes",
    stage: "Etapa",
    noApplicants: "Aún no hay solicitantes.",

    credentialingTitle: "Credenciales",
    expiringSoon: "Por vencer",
    within7Days: "En 7 días",
    within30Days: "En 30 días",
    within60Days: "En 60 días",
    expired: "Vencidas",
    noExpiring: "No hay credenciales por vencer en los próximos 60 días.",

    complianceTitle: "Revisiones de cumplimiento",
    reviewType: "Revisión",
    lastPerformed: "Última realizada",
    nextDue: "Próxima fecha",
    overdue: "Atrasada",
    neverPerformed: "Nunca realizada",

    usersTitle: "Usuarios",
    inviteUser: "Invitar usuario",
    inviting: "Invitando…",
    role: "Función",
    changeRole: "Cambiar función",
    endSessions: "Cerrar todas las sesiones",
    endSessionsPrompt: "¿Por qué está cerrando las sesiones de este usuario?",
    endingSessions: "Cerrando sesiones…",
    initialPassword: "Contraseña inicial",
    fullName: "Nombre completo",

    loading: "Cargando…",
    none: "Ninguno",
    save: "Guardar",
    cancel: "Cancelar",
    back: "Atrás",
    somethingWentWrong: "Algo salió mal. Inténtelo de nuevo.",
};

const STRINGS: Record<Locale, Record<StringKey, string>> = { en: EN, es: ES };

/**
 * Look up a string, substituting `{named}` tokens.
 *
 * Interpolation is by name rather than position so a translation is free to reorder tokens,
 * which is the whole reason not to concatenate. A missing key falls back to English rather
 * than rendering the key itself — an operator seeing `navDashboard` on screen learns nothing,
 * and the test over `missingKeys()` is what stops it happening in the first place.
 */

/**
 * Pick the `_one` / `_other` variant of a key when a `count` token is present.
 *
 * Chosen by `Intl.PluralRules`, not by `count === 1`. English and Spanish happen to agree on
 * the boundary, so the difference is invisible today — but hardcoding it is how a codebase
 * ends up unable to add a language with a different rule without touching every call site.
 * Interpolating a bare count into a fixed sentence is the alternative, and it produces
 * "1 credenciales vencidas".
 */
function resolvePlural(
  locale: Locale,
  key: StringKey,
  tokens: Record<string, string | number>,
): string | undefined {
  if (!("count" in tokens)) return undefined;
  const count = Number(tokens.count);
  if (!Number.isFinite(count)) return undefined;

  const category = new Intl.PluralRules(locale).select(count);
  const dictionary: Record<string, string> = STRINGS[locale];
  // `other` is the fallback because every CLDR locale defines it; `one` may not exist.
  return dictionary[`${key}_${category}`] ?? dictionary[`${key}_other`];
}

export function translate(
  locale: Locale,
  key: StringKey,
  tokens: Record<string, string | number> = {},
): string {
  const template: string = resolvePlural(locale, key, tokens) ?? STRINGS[locale][key] ?? STRINGS.en[key];
  return template.replace(/\{(\w+)\}/g, (match, token: string) =>
    token in tokens ? String(tokens[token]) : match,
  );
}

export type Translator = (key: StringKey, tokens?: Record<string, string | number>) => string;

export function translatorFor(locale: Locale): Translator {
  return (key, tokens) => translate(locale, key, tokens);
}

/** The API's role identifiers mapped to their display keys. */
const ROLE_KEYS: Record<string, StringKey> = {
  owner_admin: "roleOwnerAdmin",
  scheduler: "roleScheduler",
  clinical_supervisor: "roleClinicalSupervisor",
  caregiver: "roleCaregiver",
  billing_rcm: "roleBillingRcm",
  auditor: "roleAuditor",
};

/**
 * A role's name in the reader's language.
 *
 * Falls back to the raw identifier rather than throwing: a role added to the API before it is
 * added here should render as `new_role` rather than take the page down.
 */
export function roleLabel(locale: Locale, role: string): string {
  const key = ROLE_KEYS[role];
  return key ? translate(locale, key) : role;
}

/**
 * Every locale must define every key, or the app switches language mid-screen.
 *
 * Exported so a test can assert it, in the same shape as the caregiver app's version.
 */
export function missingKeys(): { locale: Locale; key: string }[] {
  const reference = Object.keys(EN);
  const gaps: { locale: Locale; key: string }[] = [];
  for (const locale of LOCALES) {
    const defined = new Set(Object.keys(STRINGS[locale]));
    for (const key of reference) {
      if (!defined.has(key)) gaps.push({ locale, key });
    }
  }
  return gaps;
}

/**
 * Keys whose Spanish is byte-identical to the English.
 *
 * Almost always an untranslated entry copied across to satisfy `missingKeys()`. A few are
 * legitimately the same in both languages — a product name, an initialism — so this reports
 * rather than judges, and the test that reads it holds the allowed list.
 */
export function identicalToEnglish(): string[] {
  return Object.keys(EN).filter((key) => ES[key as StringKey] === EN[key as StringKey]);
}

export const ALL_KEYS = Object.keys(EN) as StringKey[];
