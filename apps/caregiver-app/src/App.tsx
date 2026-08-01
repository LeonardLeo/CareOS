import { useCallback, useEffect, useState } from "react";
import { ConnectionBar } from "@/components/ConnectionBar";
import { ApiError, type MyVisit, api } from "@/lib/api";
import { type Locale, detectLocale, storeLocale, translatorFor } from "@/lib/i18n";
import { endSession, isExpired, readToken } from "@/lib/session";
import { cacheSchedule, readCachedSchedule } from "@/lib/storage";
import { useSync } from "@/lib/useSync";
import { Login } from "@/screens/Login";
import { Today } from "@/screens/Today";
import { Visit } from "@/screens/Visit";

/**
 * Shell and routing.
 *
 * No router library: there are three screens and the app must work from a cached shell with no
 * network, so a client-side route table is one fewer thing that can fail to load. The
 * open-visit state is held here rather than in the URL, which does mean a reload returns to
 * the schedule — an acceptable trade for a two-tap app, and the schedule is where a caregiver
 * wants to land anyway.
 *
 * The load order matters more than it looks: the cached schedule is read and rendered *before*
 * the network is attempted. A caregiver opening the app in a basement sees their day
 * immediately, marked with how old it is, rather than a spinner that resolves into an error.
 */
export function App() {
  const [locale, setLocale] = useState<Locale>(detectLocale);
  const t = translatorFor(locale);

  const [signedIn, setSignedIn] = useState(() => {
    const token = readToken();
    return token !== null && !isExpired(token);
  });
  const [visits, setVisits] = useState<MyVisit[]>([]);
  const [cachedAt, setCachedAt] = useState<string | null>(null);
  const [openVisitId, setOpenVisitId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = readToken();
    if (!token) return;
    try {
      const fresh = await api.myVisits(token);
      setVisits(fresh);
      setCachedAt(null);
      await cacheSchedule(fresh);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        // Cached PHI goes with the session, per the remote-wipe requirement in
        // `08_Security_Architecture.md` Section 6. The outbox deliberately survives.
        await endSession();
        setSignedIn(false);
        setVisits([]);
        return;
      }
      // Any other failure is treated as "no network right now", which is the common case.
      const cached = await readCachedSchedule<MyVisit[]>();
      if (cached) {
        setVisits(cached.payload);
        setCachedAt(cached.cachedAt);
      }
    }
  }, []);

  // Reload after the outbox drains, so server state replaces the queued-on-device state and a
  // completed visit stops showing as pending.
  const sync = useSync(() => void load());

  useEffect(() => {
    if (!signedIn) return;
    let cancelled = false;
    void (async () => {
      const cached = await readCachedSchedule<MyVisit[]>();
      if (cached && !cancelled) {
        setVisits(cached.payload);
        setCachedAt(cached.cachedAt);
      }
      if (!cancelled) await load();
    })();
    return () => {
      cancelled = true;
    };
  }, [signedIn, load]);

  function changeLocale(next: Locale) {
    storeLocale(next);
    setLocale(next);
  }

  if (!signedIn) {
    return (
      <Login
        t={t}
        locale={locale}
        onLocaleChange={changeLocale}
        onSignedIn={() => setSignedIn(true)}
      />
    );
  }

  const openVisit = visits.find((v) => v.id === openVisitId) ?? null;

  return (
    <>
      <ConnectionBar sync={sync} t={t} />
      {openVisit ? (
        <Visit
          visit={openVisit}
          sync={sync}
          onBack={() => setOpenVisitId(null)}
          t={t}
          locale={locale}
        />
      ) : (
        <Today
          visits={visits}
          queued={sync.pending}
          cachedAt={cachedAt}
          onOpen={(visit) => setOpenVisitId(visit.id)}
          onSignOut={async () => {
            await endSession();
            setSignedIn(false);
            setVisits([]);
            setOpenVisitId(null);
          }}
          t={t}
          locale={locale}
        />
      )}
    </>
  );
}
