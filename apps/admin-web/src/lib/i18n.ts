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
 * worse than one that only speaks English. Two things keep that from happening quietly: `ES` is
 * annotated `Record<StringKey, string>`, so a key added here and forgotten there is a compile
 * error, and `npm run i18n:check` — wired into CI — fails on user-facing text that never
 * reached this file at all. `missingKeys()` and `identicalToEnglish()` are exported for a
 * runtime check; nothing calls them today, and the compiler covers the first of the two.
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
    signInDisabled: "This account has been disabled. Contact your agency administrator.",
    signInUnavailable: "Could not sign in. Please try again.",
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
    schedulingSubtitle: "Unfilled shifts over the next two weeks, most urgent first.",
    caregiverAssignedNote: "The caregiver has been assigned to that visit.",
    couldNotAssign: "That caregiver could not be assigned",
    next7Days: "Next 7 days",
    next7DaysSubtitle:
      "Each mark is a visit, positioned by time of day. Clusters of unfilled visits show up as vertical runs.",
    unfilledShifts: "Unfilled shifts",
    soonestFirst: "Soonest first",
    noUnfilledShifts: "No unfilled shifts",
    everyVisitAssigned2Weeks: "Every visit in the next two weeks has a caregiver assigned.",
    unfilledShifts2WeeksCaption: "Unfilled shifts in the next two weeks",
    selectUnfilledShift: "Select an unfilled shift",
    selectShiftDetail: "Ranked caregivers and the reasoning behind each score will appear here.",
    nobodyCanTakeVisit: "Nobody can take this visit right now",
    nobodyCanTakeDetail:
      "Everyone is unavailable, double-booked, or blocked by a compliance gate — an uncleared exclusion check or an expired credential. Check the credentialing queue.",
    suggestions: "Suggestions",
    onlyCompliantListed: "{when} · only caregivers who pass every compliance gate are listed",
    factorsConsidered: "{count} factors considered",
    assignNamed: "Assign {name}",
    couldNotLoadScheduling: "Could not load scheduling data.",

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
    newClientSubtitle:
      "Date of birth and street address are encrypted before they are stored. Coordinates are held separately and coarsely, because the visit geofence rule computes against them.",
    clientDetails: "Client details",
    streetAddress: "Street address",
    latitude: "Latitude",
    longitude: "Longitude",
    serviceStateHint: "Selects the EVV aggregator and the compliance rule set that apply.",
    primaryPayer: "Primary payer",
    payerMedicaidWaiver: "Medicaid waiver",
    payerMedicareAdvantage: "Medicare Advantage",
    payerPrivatePay: "Private pay",
    payerOther: "Other",
    primaryPayerHint:
      "Publicly-funded payers require a cleared OIG/GSA exclusion check before any caregiver can be assigned.",

    newClient: "New client",
    createClient: "Create client",
    creating: "Creating…",
    clientName: "Legal name",
    clientDob: "Date of birth",
    clientAddress: "Address",
    serviceState: "Service state",
    payerType: "Payer type",
    carePlans: "Care plans",
    backToClients: "Back to clients",
    generated: "Generated",
    couldNotCompleteStep: "Could not complete that step",
    step1CarePlan: "1. Care plan",
    step2GenerateVisits: "2. Generate visits",
    existingPlans_one: "{count} existing plan — creating another adds to them",
    existingPlans_other: "{count} existing plans — creating another adds to them",
    authorizedTasksAndRecurrence: "Authorized tasks and how often visits recur",
    recurrence: "Recurrence",
    recurDaily30: "Daily, 30 visits",
    recurMwf24: "Mon / Wed / Fri, 24 visits",
    recurWeekdays40: "Weekdays, 40 visits",
    recurWeekends16: "Weekends, 16 visits",
    startHour: "Start hour",
    effectiveFrom: "Effective from",
    serviceCode: "Service code",
    serviceCodeHint:
      "Must exist in the reference table for this state and payer. Codes vary by state and waiver program, so an unconfigured code is rejected with an explanation rather than silently accepted.",
    authorizedTask: "Authorized task",
    credentialTaskRequires: "Credential this task requires",
    credentialTaskHint:
      "Used by shift matching: a caregiver without a valid credential of this type is not suggested.",
    createCarePlan: "Create care plan",
    generateVisitsSubtitle: "Materialize the recurrence into concrete, assignable visits",
    createCarePlanFirst:
      "Create a care plan first. Its recurrence rule is what visits are generated from.",
    from: "From",
    to: "To",
    visitLengthMinutes: "Visit length (minutes)",
    safeToRerun:
      "Safe to re-run: visits already generated for the same start time are not duplicated.",
    couldNotLoadClient: "Could not load this client.",
    clientLabel: "Client",

    noCarePlans: "No care plan yet. A visit cannot be scheduled without one.",
    authorizedTasks: "Authorized tasks",
    generateVisits: "Generate visits",
    noClients: "No clients yet.",

    clientsSubtitle:
      "People your agency serves. Each needs a care plan before visits can be generated.",
    addClient: "Add client",
    created: "Created",
    clientAddedNext: "Client added. Create a care plan next so visits can be generated.",
    carePlan: "Care plan",
    couldNotSaveClient: "Could not save that client",
    roster: "Roster",
    noClientsYet: "No clients yet",
    noClientsDetail:
      "Add a client, give them a care plan, then generate their recurring visits.",
    clientRoster: "Client roster",
    clientCount_one: "{count} client",
    clientCount_other: "{count} clients",
    colName: "Name",
    colState: "State",
    colPayer: "Payer",
    colAdded: "Added",
    couldNotLoadClients: "Could not load clients.",

    // --- Exceptions
    exceptionsTitle: "Compliance exceptions",
    exceptionsSubtitle:
      "Open findings from the rules engine and the EVV transmission worker. Critical items block billing or mean a caregiver cannot legally work the visit.",
    resolved: "Resolved",
    exceptionClosedNote: "That exception has been closed and the action recorded in the audit log.",
    markResolved: "Mark resolved",
    couldNotResolveException: "Could not resolve that exception",
    open: "Open",
    critical: "Critical",
    blocksBillingOrScheduling: "Blocks billing or scheduling",
    warning: "Warning",
    info: "Info",
    queue: "Queue",
    queueSubtitle:
      "Most severe first, then oldest first — an exception that has sat for a week outranks one raised an hour ago",
    noOpenExceptions: "No open compliance exceptions",
    noOpenExceptionsDetail:
      "Every visit's EVV record, credentials and screening are in order. This queue is empty most of the time — that is the intended state, not a missing page.",
    whatWasDone: "What was done? (optional)",
    resolutionNote: "Resolution note",
    couldNotLoadExceptions: "Could not load the exception queue.",

    noExceptions: "No open exceptions.",
    resolve: "Resolve",
    resolving: "Resolving…",
    resolution: "How was this resolved?",
    raisedOn: "Raised {date}",
    severity: "Severity",

    outOf100MatchScore: "out of 100 match score",
    noVisits: "No visits",
    unfilled: "Unfilled",
    // --- Recruiting
    recruitingSubtitle: "Pipeline health and applicant ranking.",
    funnelSubtitle:
      "Counts are cumulative — someone hired also passed screening — so conversion measures progression, not who is sitting in a stage.",
    jobPostings: "Job postings",
    noJobPostings: "No job postings yet",
    createOneToCollect: "Create one to start collecting applicants.",
    rankingSubtitle:
      "Ranked on certification match, proximity to open shifts, and availability. Protected attributes are never used.",
    noApplicantsForPosting: "No applicants yet for this posting",
    any: "Any",
    notRanked: "Not ranked",
    couldNotLoadRecruiting: "Could not load recruiting data.",

    recruitingTitle: "Recruiting",
    postingCount: "{count} total",
    colTitle: "Title",
    colRequiredCredentials: "Required credentials",
    viewing: "Viewing",
    viewApplicants: "View applicants",
    applicantsFor: "Applicants — {posting}",
    viaSource: "via {source}",
    claimsCredentials: " · claims {credentials}",
    rankedByModel:
      "Ranked by model {version}. Scores are advisory — hiring decisions remain with your team.",

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

    complianceSubtitle: "Review cadence from the compliance requirements. {outstanding} of {total} need attention.",
    reviewStanding: "Review standing",
    reviewStandingSubtitle: "A review that has never been performed is listed, not omitted",
    colOutcome: "Outcome",
    never: "Never",
    eventTriggered: "Event-triggered",
    current: "Current",
    beforeGoingLive: "Before going live",
    beforeGoingLiveBody:
      "Healthcare-compliance counsel must review the EVV and HIPAA implementation before Phase 1 launch, and the AI hiring bias audit must be run on real outcomes before ranking influences hiring decisions. Run the audit with {command}; it records its outcome here automatically.",
    couldNotLoadCompliance: "Could not load compliance data.",
    reviewHealthcareCounsel: "Healthcare compliance counsel review",
    reviewConsentLawState: "State consent-law review (ambient documentation)",
    reviewBillingCodingConsultant: "Certified billing / coding consultant review",
    reviewAiHiringBiasAudit: "AI hiring bias audit",
    reviewCmsPpsRuleReview: "CMS Home Health PPS rule review",
    reviewEvvVendorReview: "State EVV vendor assignment review",
    reviewNewStateEntry: "New state entry check",
    reviewSecurityPenetrationTest: "Security penetration test",
    // --- Credentialing
    credentialingSubtitle:
      "Renewal queue. A caregiver whose credential has expired cannot be assigned to a visit.",
    expiringWithin7: "Expiring within 7 days",
    expiringWithin30: "Expiring within 30 days",
    expiringWithin60: "Expiring within 60 days",
    noExpiredCredentials: "No expired credentials",
    nothingExpiringThisWeek: "Nothing expiring this week",
    nothingExpiringThisMonth: "Nothing expiring this month",
    nothingOn60DayHorizon: "Nothing on the 60-day horizon",
    blockingAssignmentNow: "Blocking assignment right now",
    couldNotLoadCredentialing: "Could not load credentialing data.",
    colExpiryDate: "Expiry date",

    // --- Compliance
    complianceTitle: "Compliance reviews",
    reviewType: "Review",
    lastPerformed: "Last performed",
    nextDue: "Next due",
    overdue: "Overdue",
    neverPerformed: "Never performed",

    // --- Users
    usersTitle: "Users",
    usersSubtitle:
      "Everyone who can sign in to this agency, and what each of them can reach.",
    invited: "Invited",
    canSignInNow: "They can sign in now with the password you set.",
    updated: "Updated",
    roleChangedNote: "Role changed, and the change is recorded in the audit log.",
    accessEnded: "Access ended",
    accessEndedNote:
      "Every device they were signed in on stops working on its next request, and cached client details are cleared.",
    mfaNotEnrolled: "MFA not enrolled",
    saveRole: "Save role",
    everyoneWithAccess: "Everyone with access",
    everyoneWithAccessSubtitle:
      "Role decides what each person can reach; ending sessions does not delete the account",
    noUsersYet: "No users yet",
    reasonRecorded: "Reason (recorded)",
    inviteSomeone: "Invite someone",
    theySignInWithPassword: "They sign in with the password you set here",
    sendInvitation: "Send invitation",
    ownerAdminOnly: "Owner / Admin only",
    canSeeNotChange: "Your role can see who has access but not change it.",
    initialPasswordHint:
      "At least 12 characters. Shown rather than hidden so you can pass it on without a typo — they should change it after signing in.",
    couldNotLoadUsers: "Could not load users",

    inviteUser: "Invite user",
    inviting: "Inviting…",
    role: "Role",
    changeRole: "Change role",
    endSessions: "End all sessions",
    endSessionsPrompt: "Why are you ending this user's sessions?",
    endingSessions: "Ending sessions…",
    disableAccount: "Disable account",
    enableAccount: "Enable account",
    accountDisabled: "Account disabled",
    accountEnabled: "Account enabled",
    accountDisabledNote:
      "They are signed out everywhere and cannot sign in again until the account is enabled.",
    accountEnabledNote: "They can sign in again. Sessions ended earlier stay ended.",
    disabledBecause: "Disabled: {reason}",
    disableReasonLabel: "Reason for disabling {email}",
    endSessionsReasonLabel: "Reason for ending {email}'s sessions",
    roleForUser: "Role for {email}",
    sessionsEndedAt:
      "Sessions ended {when}. They can sign in again — this ends sessions, it does not disable the account.",
    usersOverview_one:
      "{count} account, {live} able to sign in. Ending sessions signs someone out everywhere; disabling the account also stops them signing back in.",
    usersOverview_other:
      "{count} accounts, {live} able to sign in. Ending sessions signs someone out everywhere; disabling the account also stops them signing back in.",
    you: "you",
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
 * The base name of a pluralized entry — `clientCount` for `clientCount_one` / `_other`.
 *
 * Derived from the keys rather than declared, so a new plural pair becomes callable without a
 * second list to keep in step, and a base name with no `_other` variant is a type error at the
 * call site instead of an `undefined` on screen.
 */
export type PluralKey = keyof typeof EN extends infer K
  ? K extends `${infer Base}_other`
    ? Base
    : never
  : never;

/** Anything `translate` will accept. */
export type TranslatableKey = StringKey | PluralKey;

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
    signInDisabled:
      "Esta cuenta ha sido desactivada. Comuníquese con el administrador de su agencia.",
    signInUnavailable: "No se pudo iniciar sesión. Inténtelo de nuevo.",
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
    schedulingSubtitle: "Turnos sin cubrir en las próximas dos semanas, los más urgentes primero.",
    caregiverAssignedNote: "El cuidador ha sido asignado a esa visita.",
    couldNotAssign: "No se pudo asignar a ese cuidador",
    next7Days: "Próximos 7 días",
    next7DaysSubtitle:
      "Cada marca es una visita, ubicada según la hora del día. Los grupos de visitas sin cubrir aparecen como series verticales.",
    unfilledShifts: "Turnos sin cubrir",
    soonestFirst: "Los más cercanos primero",
    noUnfilledShifts: "No hay turnos sin cubrir",
    everyVisitAssigned2Weeks: "Todas las visitas de las próximas dos semanas tienen cuidador asignado.",
    unfilledShifts2WeeksCaption: "Turnos sin cubrir en las próximas dos semanas",
    selectUnfilledShift: "Seleccione un turno sin cubrir",
    selectShiftDetail:
      "Aquí aparecerán los cuidadores clasificados y el razonamiento de cada puntuación.",
    nobodyCanTakeVisit: "Nadie puede tomar esta visita en este momento",
    nobodyCanTakeDetail:
      "Todos están no disponibles, con doble reserva o bloqueados por un control de cumplimiento — una verificación de exclusión sin aprobar o una credencial vencida. Revise la cola de credenciales.",
    suggestions: "Sugerencias",
    onlyCompliantListed:
      "{when} · solo se listan los cuidadores que superan todos los controles de cumplimiento",
    factorsConsidered: "{count} factores considerados",
    assignNamed: "Asignar a {name}",
    couldNotLoadScheduling: "No se pudieron cargar los datos de horarios.",

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
    newClientSubtitle:
      "La fecha de nacimiento y la dirección se cifran antes de almacenarse. Las coordenadas se guardan por separado y de forma aproximada, porque la regla de geocerca de la visita se calcula sobre ellas.",
    clientDetails: "Datos del cliente",
    streetAddress: "Dirección",
    latitude: "Latitud",
    longitude: "Longitud",
    serviceStateHint: "Determina el agregador de EVV y el conjunto de reglas de cumplimiento aplicables.",
    primaryPayer: "Pagador principal",
    payerMedicaidWaiver: "Exención de Medicaid",
    payerMedicareAdvantage: "Medicare Advantage",
    payerPrivatePay: "Pago privado",
    payerOther: "Otro",
    primaryPayerHint:
      "Los pagadores con fondos públicos requieren una verificación de exclusión OIG/GSA aprobada antes de poder asignar a un cuidador.",

    newClient: "Nuevo cliente",
    createClient: "Crear cliente",
    creating: "Creando…",
    clientName: "Nombre legal",
    clientDob: "Fecha de nacimiento",
    clientAddress: "Dirección",
    serviceState: "Estado de servicio",
    payerType: "Tipo de pagador",
    carePlans: "Planes de cuidado",
    backToClients: "Volver a clientes",
    generated: "Generadas",
    couldNotCompleteStep: "No se pudo completar ese paso",
    step1CarePlan: "1. Plan de cuidado",
    step2GenerateVisits: "2. Generar visitas",
    existingPlans_one: "{count} plan existente — crear otro se suma a los actuales",
    existingPlans_other: "{count} planes existentes — crear otro se suma a los actuales",
    authorizedTasksAndRecurrence: "Tareas autorizadas y frecuencia de las visitas",
    recurrence: "Recurrencia",
    recurDaily30: "Diaria, 30 visitas",
    recurMwf24: "Lunes / miércoles / viernes, 24 visitas",
    recurWeekdays40: "Días laborables, 40 visitas",
    recurWeekends16: "Fines de semana, 16 visitas",
    startHour: "Hora de inicio",
    effectiveFrom: "Vigente desde",
    serviceCode: "Código de servicio",
    serviceCodeHint:
      "Debe existir en la tabla de referencia para este estado y pagador. Los códigos varían según el estado y el programa de exención, por lo que un código no configurado se rechaza con una explicación en lugar de aceptarse en silencio.",
    authorizedTask: "Tarea autorizada",
    credentialTaskRequires: "Credencial que requiere esta tarea",
    credentialTaskHint:
      "La usa la asignación de turnos: un cuidador sin una credencial válida de este tipo no se sugiere.",
    createCarePlan: "Crear plan de cuidado",
    generateVisitsSubtitle: "Convertir la recurrencia en visitas concretas y asignables",
    createCarePlanFirst:
      "Cree primero un plan de cuidado. Su regla de recurrencia es la base para generar las visitas.",
    from: "Desde",
    to: "Hasta",
    visitLengthMinutes: "Duración de la visita (minutos)",
    safeToRerun:
      "Se puede volver a ejecutar sin riesgo: las visitas ya generadas para la misma hora de inicio no se duplican.",
    couldNotLoadClient: "No se pudo cargar este cliente.",
    clientLabel: "Cliente",

    noCarePlans: "Aún no hay plan de cuidado. No se puede programar una visita sin uno.",
    authorizedTasks: "Tareas autorizadas",
    generateVisits: "Generar visitas",
    noClients: "Aún no hay clientes.",

    clientsSubtitle:
      "Personas a las que atiende su agencia. Cada una necesita un plan de cuidado antes de poder programar visitas.",
    addClient: "Agregar cliente",
    created: "Creado",
    clientAddedNext:
      "Cliente agregado. Cree un plan de cuidado para poder generar visitas.",
    carePlan: "Plan de cuidado",
    couldNotSaveClient: "No se pudo guardar ese cliente",
    roster: "Lista",
    noClientsYet: "Aún no hay clientes",
    noClientsDetail:
      "Agregue un cliente, asígnele un plan de cuidado y luego genere sus visitas recurrentes.",
    clientRoster: "Lista de clientes",
    clientCount_one: "{count} cliente",
    clientCount_other: "{count} clientes",
    colName: "Nombre",
    colState: "Estado",
    colPayer: "Pagador",
    colAdded: "Agregado",
    couldNotLoadClients: "No se pudieron cargar los clientes.",

    exceptionsTitle: "Excepciones de cumplimiento",
    exceptionsSubtitle:
      "Hallazgos abiertos del motor de reglas y del proceso de transmisión de EVV. Los elementos críticos impiden la facturación o significan que un cuidador no puede trabajar legalmente la visita.",
    resolved: "Resuelta",
    exceptionClosedNote:
      "Esa excepción se cerró y la acción quedó registrada en el registro de auditoría.",
    markResolved: "Marcar como resuelta",
    couldNotResolveException: "No se pudo resolver esa excepción",
    open: "Abiertas",
    critical: "Crítica",
    blocksBillingOrScheduling: "Impide la facturación o la programación",
    warning: "Advertencia",
    info: "Información",
    queue: "Cola",
    queueSubtitle:
      "Las más graves primero, luego las más antiguas — una excepción que lleva una semana pendiente tiene prioridad sobre una registrada hace una hora",
    noOpenExceptions: "No hay excepciones de cumplimiento abiertas",
    noOpenExceptionsDetail:
      "El registro de EVV, las credenciales y las verificaciones de cada visita están en orden. Esta cola está vacía la mayor parte del tiempo — ese es el estado esperado, no una página faltante.",
    whatWasDone: "¿Qué se hizo? (opcional)",
    resolutionNote: "Nota de resolución",
    couldNotLoadExceptions: "No se pudo cargar la cola de excepciones.",

    noExceptions: "No hay excepciones abiertas.",
    resolve: "Resolver",
    resolving: "Resolviendo…",
    resolution: "¿Cómo se resolvió?",
    raisedOn: "Registrada el {date}",
    severity: "Gravedad",

    outOf100MatchScore: "de 100 en la puntuación de coincidencia",
    noVisits: "Sin visitas",
    unfilled: "Sin cubrir",
    recruitingSubtitle: "Estado del proceso y clasificación de solicitantes.",
    funnelSubtitle:
      "Los conteos son acumulativos — quien fue contratado también pasó la verificación — por lo que la conversión mide el avance, no cuántos están en cada etapa.",
    jobPostings: "Publicaciones de empleo",
    noJobPostings: "Aún no hay publicaciones de empleo",
    createOneToCollect: "Cree una para empezar a recibir solicitantes.",
    rankingSubtitle:
      "Clasificados por coincidencia de certificaciones, cercanía a los turnos abiertos y disponibilidad. Nunca se usan atributos protegidos.",
    noApplicantsForPosting: "Aún no hay solicitantes para esta publicación",
    any: "Cualquiera",
    notRanked: "Sin clasificar",
    couldNotLoadRecruiting: "No se pudieron cargar los datos de contratación.",

    recruitingTitle: "Contratación",
    postingCount: "{count} en total",
    colTitle: "Título",
    colRequiredCredentials: "Credenciales requeridas",
    viewing: "Viendo",
    viewApplicants: "Ver solicitantes",
    applicantsFor: "Solicitantes — {posting}",
    viaSource: "vía {source}",
    claimsCredentials: " · declara {credentials}",
    rankedByModel:
      "Clasificado por el modelo {version}. Las puntuaciones son orientativas — las decisiones de contratación siguen siendo de su equipo.",

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

    complianceSubtitle: "Ciclo de revisiones según los requisitos de cumplimiento. {outstanding} de {total} requieren atención.",
    reviewStanding: "Estado de las revisiones",
    reviewStandingSubtitle: "Una revisión que nunca se ha realizado aparece en la lista, no se omite",
    colOutcome: "Resultado",
    never: "Nunca",
    eventTriggered: "Activada por evento",
    current: "Al día",
    beforeGoingLive: "Antes de la puesta en marcha",
    beforeGoingLiveBody:
      "Un asesor legal de cumplimiento sanitario debe revisar la implementación de EVV y HIPAA antes del lanzamiento de la Fase 1, y la auditoría de sesgo del modelo de contratación debe ejecutarse sobre resultados reales antes de que la clasificación influya en las decisiones de contratación. Ejecute la auditoría con {command}; registra su resultado aquí automáticamente.",
    couldNotLoadCompliance: "No se pudieron cargar los datos de cumplimiento.",
    reviewHealthcareCounsel: "Revisión de asesoría legal en cumplimiento sanitario",
    reviewConsentLawState: "Revisión de la ley de consentimiento estatal (documentación ambiental)",
    reviewBillingCodingConsultant: "Revisión de consultor certificado en facturación y codificación",
    reviewAiHiringBiasAudit: "Auditoría de sesgo en contratación con IA",
    reviewCmsPpsRuleReview: "Revisión de la norma PPS de atención domiciliaria de CMS",
    reviewEvvVendorReview: "Revisión de asignación de proveedor EVV estatal",
    reviewNewStateEntry: "Verificación de entrada a un nuevo estado",
    reviewSecurityPenetrationTest: "Prueba de penetración de seguridad",
    credentialingSubtitle:
      "Cola de renovaciones. Un cuidador cuya credencial ha vencido no puede asignarse a una visita.",
    expiringWithin7: "Vencen en 7 días",
    expiringWithin30: "Vencen en 30 días",
    expiringWithin60: "Vencen en 60 días",
    noExpiredCredentials: "No hay credenciales vencidas",
    nothingExpiringThisWeek: "Nada vence esta semana",
    nothingExpiringThisMonth: "Nada vence este mes",
    nothingOn60DayHorizon: "Nada en el horizonte de 60 días",
    blockingAssignmentNow: "Impide la asignación ahora mismo",
    couldNotLoadCredentialing: "No se pudieron cargar los datos de credenciales.",
    colExpiryDate: "Fecha de vencimiento",

    complianceTitle: "Revisiones de cumplimiento",
    reviewType: "Revisión",
    lastPerformed: "Última realizada",
    nextDue: "Próxima fecha",
    overdue: "Atrasada",
    neverPerformed: "Nunca realizada",

    usersTitle: "Usuarios",
    usersSubtitle:
      "Todas las personas que pueden iniciar sesión en esta agencia y a qué puede acceder cada una.",
    invited: "Invitado",
    canSignInNow: "Ya puede iniciar sesión con la contraseña que estableció.",
    updated: "Actualizado",
    roleChangedNote: "Función cambiada; el cambio queda registrado en el registro de auditoría.",
    accessEnded: "Acceso finalizado",
    accessEndedNote:
      "Todos los dispositivos en los que había iniciado sesión dejan de funcionar en su siguiente solicitud, y los datos de clientes en caché se borran.",
    mfaNotEnrolled: "Sin autenticación de múltiples factores",
    saveRole: "Guardar función",
    everyoneWithAccess: "Todas las personas con acceso",
    everyoneWithAccessSubtitle:
      "La función determina a qué puede acceder cada persona; cerrar las sesiones no elimina la cuenta",
    noUsersYet: "Aún no hay usuarios",
    reasonRecorded: "Motivo (queda registrado)",
    inviteSomeone: "Invitar a alguien",
    theySignInWithPassword: "Iniciará sesión con la contraseña que establezca aquí",
    sendInvitation: "Enviar invitación",
    ownerAdminOnly: "Solo propietario / administrador",
    canSeeNotChange: "Su función permite ver quién tiene acceso, pero no modificarlo.",
    initialPasswordHint:
      "Al menos 12 caracteres. Se muestra en lugar de ocultarse para que pueda transmitirla sin errores — la persona debería cambiarla después de iniciar sesión.",
    couldNotLoadUsers: "No se pudieron cargar los usuarios",

    inviteUser: "Invitar usuario",
    inviting: "Invitando…",
    role: "Función",
    changeRole: "Cambiar función",
    endSessions: "Cerrar todas las sesiones",
    endSessionsPrompt: "¿Por qué está cerrando las sesiones de este usuario?",
    endingSessions: "Cerrando sesiones…",
    disableAccount: "Desactivar cuenta",
    enableAccount: "Activar cuenta",
    accountDisabled: "Cuenta desactivada",
    accountEnabled: "Cuenta activada",
    accountDisabledNote:
      "Se cierra su sesión en todos los dispositivos y no podrá volver a iniciar sesión hasta que se active la cuenta.",
    accountEnabledNote:
      "Ya puede volver a iniciar sesión. Las sesiones cerradas anteriormente siguen cerradas.",
    disabledBecause: "Desactivada: {reason}",
    disableReasonLabel: "Motivo para desactivar la cuenta de {email}",
    endSessionsReasonLabel: "Motivo para cerrar las sesiones de {email}",
    roleForUser: "Función de {email}",
    sessionsEndedAt:
      "Sesiones cerradas el {when}. Puede volver a iniciar sesión — esto cierra las sesiones, no desactiva la cuenta.",
    usersOverview_one:
      "{count} cuenta, {live} puede iniciar sesión. Cerrar las sesiones desconecta a la persona de todos los dispositivos; desactivar la cuenta además le impide volver a entrar.",
    usersOverview_other:
      "{count} cuentas, {live} pueden iniciar sesión. Cerrar las sesiones desconecta a la persona de todos los dispositivos; desactivar la cuenta además le impide volver a entrar.",
    you: "usted",
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
  key: TranslatableKey,
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
  key: TranslatableKey,
  tokens: Record<string, string | number> = {},
): string {
  const plural = resolvePlural(locale, key, tokens);
  if (plural !== undefined) return interpolate(plural, tokens);
  const direct = STRINGS[locale] as Record<string, string>;
  const fallback = STRINGS.en as Record<string, string>;
  // The `?? key` tail is unreachable for a `StringKey` — the compiler guarantees both
  // dictionaries define it — and exists only so a `PluralKey` used without a `count` token
  // degrades to something visible rather than the string "undefined".
  const template: string = direct[key] ?? fallback[key] ?? key;
  return interpolate(template, tokens);
}

function interpolate(template: string, tokens: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, token: string) =>
    token in tokens ? String(tokens[token]) : match,
  );
}

export type Translator = (
  key: TranslatableKey,
  tokens?: Record<string, string | number>,
) => string;

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
