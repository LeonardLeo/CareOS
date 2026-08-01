import type { Metadata } from "next";

import { LegalPage } from "@/components/legal-page";
import { CONTACT_EMAIL } from "@/content/site";

export const metadata: Metadata = {
  title: "Accessibility",
  description:
    "What CareOS builds to, what has actually been tested, and what we know is not there yet.",
};

/**
 * The accessibility statement.
 *
 * Written after the checks it describes, not before. Every claim in the "checked automatically"
 * section corresponds to a case in `scripts/a11y.mjs`, which fails the build; every claim in
 * "not tested" is there because no person has used the thing with real assistive technology,
 * and an automated pass is not a substitute for that.
 */
export default function AccessibilityPage() {
  return (
    <LegalPage
      eyebrow="Legal"
      title="Accessibility"
      lede="Our users include caregivers working one-handed in a hallway, and agency owners who have been reading spreadsheets for thirty years. What follows separates what is verified from what is intended."
      updated="31 July 2026"
    >
      <h2>The standard</h2>
      <p>
        We build to <strong>WCAG 2.1 Level AA</strong> across this website, the agency
        application, and the caregiver app. Where we fall short of it we would rather say so on
        this page than describe ourselves as &ldquo;committed to accessibility&rdquo; and leave
        you to discover the gap.
      </p>

      <h2>Checked automatically, on every change</h2>
      <p>
        These are not aspirations. Each one is a test that fails the build, run against the
        rendered pages at a desktop and a phone width:
      </p>
      <ul>
        <li>
          <strong>Contrast.</strong> Every rendered piece of text is measured against the
          background actually behind it — through transparency, not against the theme colour it
          was supposed to have — at 4.5:1, or 3:1 for large text.
        </li>
        <li>
          <strong>Keyboard.</strong> The first press of Tab lands on a skip link, that link has a
          visible focus ring, and activating it genuinely moves focus into the main region. The
          check uses real key events, because a scripted <code>focus()</code> call would pass
          while the tab order was wrong.
        </li>
        <li>
          <strong>Names.</strong> Every link and button resolves to a non-empty accessible name;
          every form control resolves to a label.
        </li>
        <li>
          <strong>Structure.</strong> One <code>h1</code> per page, no heading level skipped, a{" "}
          <code>main</code> landmark, a language on the document, an <code>alt</code> attribute on
          every image, and no positive <code>tabindex</code> anywhere.
        </li>
      </ul>

      <h2>Decisions we made deliberately</h2>
      <ul>
        <li>
          <strong>Reduced motion is honoured by not animating.</strong> If your system asks for
          reduced motion, the reveal animations on this site do not run faster — they do not run.
          Content is present from the first paint. Someone who set that preference usually set it
          because motion makes them unwell.
        </li>
        <li>
          <strong>Nothing here depends on JavaScript to be readable.</strong> The base state of
          every element is visible; script only ever adds the animation. A page with scripting
          off, a reader mode, or a crawler gets the whole document rather than a blank one.
        </li>
        <li>
          <strong>Colour is never the only signal.</strong> On the coverage board a gap is a
          different fill and a different label; in the exception queue a severity is a word as
          well as a colour.
        </li>
        <li>
          <strong>English and Spanish throughout</strong>, in both the agency application and the
          caregiver app, because a large share of the caregiver workforce works in Spanish and a
          translation added later is a translation that fits badly.
        </li>
        <li>
          <strong>Text scales.</strong> Type and spacing are set in relative units, so a browser
          or OS text-size setting enlarges the layout rather than clipping it.
        </li>
        <li>
          <strong>Contact does not require a form.</strong> Every route to us is also a plain
          email address, so nothing depends on a widget behaving with your assistive technology.
        </li>
      </ul>

      <h2>What has not been tested</h2>
      <p>
        An automated pass tells you a label exists. It does not tell you the label is useful, that
        the reading order makes sense, or that a status message announces at a helpful moment.
        Those need a person using real assistive technology, and as of the date above:
      </p>
      <ul>
        <li>
          <strong>No screen-reader testing on real assistive technology.</strong> Not with VoiceOver
          on iOS, not with TalkBack, not with NVDA or JAWS.
        </li>
        <li>
          <strong>No independent accessibility audit.</strong> Nobody outside the team has assessed
          this, and we have not commissioned one.
        </li>
        <li>
          <strong>No testing with the people who will use it.</strong> The caregiver app in
          particular is designed for low-literacy and low-vision use and has never been in front of
          a caregiver who has those needs. That is the gap we are least comfortable with.
        </li>
        <li>
          <strong>The caregiver app is unverified on real devices.</strong> Offline clock-in is
          tested in a desktop browser at a phone viewport. That is not iOS Safari, a real GPS chip,
          or a phone in a pocket in a hallway with one bar of signal.
        </li>
      </ul>
      <p>
        Until those are done, we describe this as WCAG 2.1 AA as a build target with automated
        conformance checks — not as a conformance claim. The difference matters to anyone relying
        on it.
      </p>

      <h2>If something blocks you</h2>
      <p>
        Tell us and we will fix it, and we will tell you when. Write to{" "}
        <a className="textlink" href={`mailto:${CONTACT_EMAIL}`}>
          {CONTACT_EMAIL}
        </a>{" "}
        with the page or screen, what you were trying to do, and what you use — that last part
        saves a round trip. If you need something here in another format, ask and we will produce
        it rather than pointing you at a converter.
      </p>
      <p>
        Reports about accessibility get the same response times as anything else that blocks
        work, and a barrier that stops someone completing a visit is treated as urgent.
      </p>
    </LegalPage>
  );
}
