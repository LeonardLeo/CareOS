import { LOCALES, LOCALE_LABEL, type Locale, translate } from "@/lib/i18n";

/**
 * Language switcher for the sidebar.
 *
 * One submit button per language rather than a `<select>` that needs JavaScript to act on a
 * change. This app ships no client bundle for its pages, and a control that silently does
 * nothing without hydration is worse than one that looks plainer.
 *
 * The current language is a `aria-current` button rather than a disabled one: disabled
 * controls are skipped by some screen-reader navigation, so a user could not tell which
 * language is active.
 */
export function LanguageSwitcher({ locale, returnTo }: { locale: Locale; returnTo: string }) {
  return (
    <form
      className="langswitch"
      method="post"
      action="/api/locale"
      aria-label={translate(locale, "changeLanguage")}
    >
      <input type="hidden" name="returnTo" value={returnTo} />
      <span className="langswitch__label">{translate(locale, "language")}</span>
      <span className="langswitch__options">
        {LOCALES.map((option) => (
          <button
            key={option}
            className="langswitch__option"
            type="submit"
            name="locale"
            value={option}
            aria-current={option === locale ? "true" : undefined}
            // The language of the label is not the language of the page, so each is tagged.
            // Without it a screen reader reads "Español" with an English voice.
            lang={option}
          >
            {LOCALE_LABEL[option]}
          </button>
        ))}
      </span>
    </form>
  );
}
