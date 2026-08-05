/**
 * Sign-up, step one: who the agency is.
 *
 * Validates, merges into the draft cookie, and redirects to step two. Redirects carry an
 * error *code* rather than a sentence, so the page renders the message in the reader's
 * language — the same rule the sign-in handler follows, and for the same reason.
 */
import { NextResponse } from "next/server";
import {
  EMPTY_DRAFT,
  US_STATES,
  getSignupDraft,
  setSignupDraft,
} from "@/lib/signup-draft";

export async function POST(request: Request) {
  const form = await request.formData();
  const legalName = String(form.get("legal_name") ?? "").trim();
  // Only codes the closed list recognises. The API validates the shape again; this is what
  // keeps the review on step three describing something real.
  const chosen = new Set(form.getAll("service_states").map(String));
  const serviceStates = US_STATES.filter((code) => chosen.has(code));

  if (!legalName) return back(request, 1, "name");
  if (serviceStates.length === 0) return back(request, 1, "states");

  const existing = (await getSignupDraft()) ?? EMPTY_DRAFT;
  await setSignupDraft({ ...existing, legalName, serviceStates: [...serviceStates] });
  return NextResponse.redirect(new URL("/signup?step=2", request.url), { status: 303 });
}

function back(request: Request, step: number, error: string) {
  return NextResponse.redirect(new URL(`/signup?step=${step}&error=${error}`, request.url), {
    status: 303,
  });
}
