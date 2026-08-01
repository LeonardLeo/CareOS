"use client";

import { useState } from "react";

import { CONTACT_EMAIL } from "@/content/site";

/**
 * The enquiry form.
 *
 * It composes a message and hands it to the visitor's mail client. It does not post anywhere,
 * and that is a deliberate choice rather than a limitation we are working around.
 *
 * The alternatives were a third-party form service — which would put an agency owner's name
 * and their state's Medicaid programme through a company we have no agreement with, on a site
 * that otherwise makes no third-party request — or a backend endpoint, which means a server
 * for a page that has no other reason to need one. Neither is worth it before there is a
 * customer. When there is a CRM, this component gets a `fetch` and nothing else changes.
 *
 * The mail client opening *is* the confirmation. A form that shows "thanks, we'll be in touch"
 * without having sent anything is the failure this avoids.
 */
export function ContactForm() {
  const [sent, setSent] = useState(false);

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const get = (key: string) => String(data.get(key) ?? "").trim();

    const subject = `CareOS — ${get("topic") || "enquiry"} — ${get("agency") || get("name")}`;
    const body = [
      `Name: ${get("name")}`,
      `Agency: ${get("agency")}`,
      `State(s) you bill in: ${get("state")}`,
      `Caregivers: ${get("size")}`,
      "",
      get("message"),
    ].join("\n");

    window.location.href = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(
      subject,
    )}&body=${encodeURIComponent(body)}`;
    setSent(true);
  }

  return (
    <form className="stack-4" onSubmit={onSubmit}>
      <div className="field">
        <label className="field__label" htmlFor="name">
          Your name
        </label>
        <input className="input" id="name" name="name" required autoComplete="name" />
      </div>

      <div className="field">
        <label className="field__label" htmlFor="agency">
          Agency
        </label>
        <input className="input" id="agency" name="agency" autoComplete="organization" />
      </div>

      <div style={{ display: "grid", gap: "var(--s4)", gridTemplateColumns: "1fr 1fr" }}>
        <div className="field">
          <label className="field__label" htmlFor="state">
            State you bill in
          </label>
          <input className="input" id="state" name="state" placeholder="NY" />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="size">
            Caregivers
          </label>
          <input className="input" id="size" name="size" placeholder="40" inputMode="numeric" />
        </div>
      </div>

      <div className="field">
        <label className="field__label" htmlFor="topic">
          What is this about?
        </label>
        <select className="select" id="topic" name="topic" defaultValue="design partner">
          <option value="design partner">Becoming a design partner</option>
          <option value="product question">A question about the product</option>
          <option value="security review">Security or compliance review</option>
          <option value="working together">Working at CareOS</option>
          <option value="something else">Something else</option>
        </select>
      </div>

      <div className="field">
        <label className="field__label" htmlFor="message">
          What breaks most often?
        </label>
        <textarea
          className="textarea"
          id="message"
          name="message"
          required
          placeholder="Last-minute call-outs, credential tracking, EVV rejections, onboarding taking three weeks…"
        />
        <span className="field__hint">
          Specifics help more than a summary. One real example is enough.
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "var(--s4)", flexWrap: "wrap" }}>
        <button className="btn btn--accent" type="submit">
          Open in your mail app <span className="arrow">→</span>
        </button>
        {/* Announced politely so a screen reader hears it without interrupting. */}
        <span role="status" aria-live="polite" className="field__hint">
          {sent
            ? `If nothing opened, write to ${CONTACT_EMAIL} directly.`
            : "This composes an email — nothing is sent from this page."}
        </span>
      </div>
    </form>
  );
}
