"""Populate a running local API with a plausible agency, for demos and manual review.

This drives the public HTTP API rather than writing rows directly. That is slower than a
bulk insert, and deliberate: a demo built out of direct inserts can produce states the API
would never allow, and then the screens show something the product cannot actually reach.
Everything here goes through the same validation, RBAC, and audit path a real agency would.

Not for staging or production. It creates users with known passwords.

    make demo            # with the API already running on :8000
    python -m careos.scripts.seed_demo_data --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

DEMO_PASSWORD = "demo-password-12345"
OWNER_EMAIL = "owner@bayridgecare.demo"
CAREGIVER_EMAIL = "ama.boateng@bayridgecare.demo"

# Fixed seed so repeated runs against a fresh database produce the same agency. A demo that
# reshuffles itself between runs makes screenshots and bug reports harder to compare.
RNG = random.Random(20260731)

# Brooklyn and lower Manhattan. Real coordinates, so drive-time ranking and the geofence
# radius on clock-in behave the way they would in the field rather than degenerating.
CAREGIVER_HOMES = [
    ("Ama Boateng", 40.6402, -74.0246, "8412 4th Ave, Brooklyn, NY 11209"),
    ("Rosa Delgado", 40.6501, -73.9496, "1120 Nostrand Ave, Brooklyn, NY 11225"),
    ("Grace Okonkwo", 40.6782, -73.9442, "590 Bedford Ave, Brooklyn, NY 11211"),
    ("Marisol Reyes", 40.6415, -73.9781, "1345 Ocean Pkwy, Brooklyn, NY 11230"),
    ("Fatou Diallo", 40.6936, -73.9866, "215 Adams St, Brooklyn, NY 11201"),
    ("Ingrid Sørensen", 40.6229, -74.0295, "7017 3rd Ave, Brooklyn, NY 11209"),
    ("Nadia Haddad", 40.6602, -73.9690, "425 Prospect Pl, Brooklyn, NY 11238"),
    ("Junior Alcindor", 40.6712, -73.9260, "1580 Fulton St, Brooklyn, NY 11216"),
    ("Thandiwe Moyo", 40.6317, -74.0141, "6822 Bay Pkwy, Brooklyn, NY 11204"),
    ("Precious Adeyemi", 40.6889, -73.9553, "310 Marcy Ave, Brooklyn, NY 11206"),
]

CLIENT_HOMES = [
    ("Eleanor Whitfield", 40.6461, -74.0175, "545 Ovington Ave, Brooklyn, NY 11209"),
    ("Harold Brennan", 40.6558, -73.9611, "88 Lefferts Ave, Brooklyn, NY 11225"),
    ("Sylvia Kaminski", 40.6690, -73.9502, "233 Franklin Ave, Brooklyn, NY 11205"),
    ("Arthur Mensah", 40.6376, -73.9822, "1901 Ave J, Brooklyn, NY 11230"),
    ("Doris Fitzgerald", 40.6851, -73.9905, "70 Willoughby St, Brooklyn, NY 11201"),
    ("Manuel Ortega", 40.6274, -74.0210, "1815 78th St, Brooklyn, NY 11214"),
    ("Ruth Abramowitz", 40.6635, -73.9741, "160 Sterling Pl, Brooklyn, NY 11217"),
    ("Clarence Boyd", 40.6759, -73.9312, "1245 Bergen St, Brooklyn, NY 11213"),
    ("Ida Nakamura", 40.6338, -74.0068, "1420 Bath Ave, Brooklyn, NY 11228"),
    ("Vincent Russo", 40.6920, -73.9601, "455 Broadway, Brooklyn, NY 11211"),
    ("Bernice Achebe", 40.6489, -73.9930, "4802 Fort Hamilton Pkwy, Brooklyn, NY 11219"),
    ("Stanley Kowalczyk", 40.6607, -73.9284, "1710 Eastern Pkwy, Brooklyn, NY 11233"),
]

APPLICANT_NAMES = [
    "Blessing Adeyinka",
    "Carmen Villalobos",
    "Destiny Ferguson",
    "Elena Popescu",
    "Gabriel Osei",
    "Hyacinth Charles",
    "Imani Robinson",
    "Jocelyn Mbeki",
    "Katarzyna Nowak",
    "Leticia Domínguez",
    "Miriam Yusuf",
    "Nkechi Eze",
    "Oksana Kovalenko",
    "Priya Raghunathan",
    "Rosalind Achterberg",
    "Sandra Etienne",
]

# `required_credential` is the field the assignment gate reads; the rest is descriptive.
# Two of these carry a credential requirement, which is what gives the matcher a reason to
# rule some caregivers out of some visits rather than ranking all ten every time.
AUTHORIZED_TASKS: list[dict[str, Any]] = [
    {"code": "bathing", "label": "Bathing and personal hygiene", "required_credential": "HHA"},
    {"code": "dressing", "label": "Dressing"},
    {"code": "meal_prep", "label": "Meal preparation"},
    {
        "code": "med_reminders",
        "label": "Medication reminders",
        "required_credential": "HHA",
    },
    {"code": "housekeeping", "label": "Light housekeeping"},
    {"code": "mobility", "label": "Mobility and transfer assistance"},
    {"code": "toileting", "label": "Toileting and incontinence care"},
    {"code": "companionship", "label": "Companionship"},
]

# Recurrence rules per client, so the board is not a uniform grid. Weekday mornings for
# personal care, three-times-weekly for the lighter cases, daily for the two heaviest.
FREQUENCY_RULES: list[dict[str, Any]] = [
    {"rrule": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "start_hour": 8},
    {"rrule": "FREQ=WEEKLY;BYDAY=MO,WE,FR", "start_hour": 9},
    {"rrule": "FREQ=DAILY", "start_hour": 7, "start_minute": 30},
    {"rrule": "FREQ=WEEKLY;BYDAY=TU,TH", "start_hour": 13},
    {"rrule": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "start_hour": 15},
    {"rrule": "FREQ=WEEKLY;BYDAY=SA,SU", "start_hour": 10},
]


@dataclass(slots=True)
class Api:
    """A thin authenticated client. Raises on any non-2xx so a broken demo fails loudly."""

    base_url: str
    token: str | None = None

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        # A few hundred writes in a row trips the standard-tier rate limit, which is the
        # limiter doing its job. Back off and continue rather than raising the ceiling for
        # the demo — a seed that needs the limits relaxed is testing a system nobody runs.
        for attempt in range(6):
            response = httpx.request(
                method, f"{self.base_url}{path}", headers=headers, timeout=60.0, **kwargs
            )
            if response.status_code != 429:
                break
            time.sleep(2.0 * (attempt + 1))
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {response.status_code} {response.text}")
        return response.json() if response.content else None

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self._request("POST", path, **kwargs)


def _error_code(message: str) -> str:
    """Pull the API error code out of a raised request failure, for the refusal tally."""
    marker = '"code":"'
    start = message.find(marker)
    if start == -1:
        return "unknown"
    start += len(marker)
    return message[start : message.find('"', start)]


def _credentials_for(index: int, today: date) -> list[dict[str, Any]]:
    """Credential sets that put the compliance dashboard in a realistic mixed state.

    Roughly two thirds of caregivers are clean, one has an expired certification, two are
    inside the 30-day expiry window, and one is awaiting verification. A demo where every
    row is green shows nothing about what the screen is for.
    """
    base_type = "HHA" if index % 3 else "CNA"
    creds: list[dict[str, Any]] = [
        {
            "credential_type": base_type,
            "issuing_body": "NY State Department of Health",
            "credential_number": f"NY-{base_type}-{40000 + index * 137}",
            "issue_date": (today - timedelta(days=430 + index * 11)).isoformat(),
            "expiration_date": (today + timedelta(days=300 - index * 7)).isoformat(),
            "verification_status": "verified",
        },
        {
            "credential_type": "CPR",
            "issuing_body": "American Heart Association",
            "issue_date": (today - timedelta(days=700)).isoformat(),
            "expiration_date": (today + timedelta(days=25)).isoformat(),
            "verification_status": "verified",
        },
    ]
    if index == 2:
        creds[0]["expiration_date"] = (today - timedelta(days=12)).isoformat()
        creds[0]["verification_status"] = "expired"
    elif index == 5:
        creds[1]["expiration_date"] = (today + timedelta(days=9)).isoformat()
    elif index == 7:
        creds[0]["verification_status"] = "pending"

    creds.append(
        {
            "credential_type": "TB_TEST",
            "issuing_body": "Brooklyn Occupational Health",
            "issue_date": (today - timedelta(days=200)).isoformat(),
            "expiration_date": (today + timedelta(days=165)).isoformat(),
            "verification_status": "verified",
        }
    )
    return creds


def seed(base_url: str) -> None:
    api = Api(base_url=base_url)
    today = datetime.now(UTC).date()

    agency = api.post(
        "/v1/agencies",
        json={
            "legal_name": "Bay Ridge Home Care Services LLC",
            "tax_id": "13-4592071",
            "service_states": ["NY"],
            "service_lines": ["home_care"],
            "accepted_payer_types": ["medicaid_waiver", "private_pay"],
            "owner_email": OWNER_EMAIL,
            "owner_password": DEMO_PASSWORD,
        },
    )
    agency_id = agency["id"]
    print(f"agency         {agency['legal_name']} ({agency_id})")

    tokens = api.post("/v1/auth/login", json={"email": OWNER_EMAIL, "password": DEMO_PASSWORD})
    api.token = tokens["access_token"]

    for email, role in [
        ("dana.scheduler@bayridgecare.demo", "scheduler"),
        ("rn.supervisor@bayridgecare.demo", "clinical_supervisor"),
        ("billing@bayridgecare.demo", "billing_rcm"),
    ]:
        api.post(
            f"/v1/agencies/{agency_id}/users",
            json={"email": email, "role": role, "initial_password": DEMO_PASSWORD},
        )
    print("users          4 (owner, scheduler, clinical supervisor, billing)")

    caregiver_ids: list[str] = []
    for index, (name, lat, lng, address) in enumerate(CAREGIVER_HOMES):
        # The first caregiver gets a login, so the mobile app has someone to sign in as.
        # The rest are records only, which is the ordinary case: most caregivers are onboarded
        # before they ever open the app.
        app_user_id = None
        if index == 0:
            app_user_id = api.post(
                f"/v1/agencies/{agency_id}/users",
                json={
                    "email": CAREGIVER_EMAIL,
                    "role": "caregiver",
                    "initial_password": DEMO_PASSWORD,
                },
            )["id"]
        caregiver = api.post(
            "/v1/caregivers",
            json={
                "legal_name": name,
                "dob": (today - timedelta(days=365 * (26 + index * 2) + index)).isoformat(),
                "address": address,
                "geo_lat": lat,
                "geo_lng": lng,
                "app_user_id": app_user_id,
            },
        )
        caregiver_ids.append(caregiver["id"])
        for credential in _credentials_for(index, today):
            api.post(f"/v1/caregivers/{caregiver['id']}/credentials", json=credential)
        # No OIG/GSA exclusion check means no Medicaid-funded visit, by rule. One caregiver
        # is left unchecked on purpose: that gate is invisible on a screen where every row
        # already passes it.
        if index != 4:
            api.post(
                f"/v1/caregivers/{caregiver['id']}/exclusion-check",
                json={
                    "status": "cleared",
                    "vendor_key": "oig_leie",
                    "vendor_reference": f"LEIE-DEMO-{90000 + index}",
                },
                headers={"Idempotency-Key": f"demo-exclusion-{caregiver['id']}"},
            )
    print(f"caregivers     {len(caregiver_ids)}, 3 credentials each, 9 exclusion-checked")

    care_plan_ids: list[str] = []
    for index, (name, lat, lng, address) in enumerate(CLIENT_HOMES):
        payer = "medicaid_waiver" if index % 4 else "private_pay"
        client = api.post(
            "/v1/clients",
            json={
                "legal_name": name,
                "dob": (today - timedelta(days=365 * (71 + index) + index * 3)).isoformat(),
                "address": address,
                "geo_lat": lat,
                "geo_lng": lng,
                "service_state": "NY",
                "primary_payer_type": payer,
            },
        )
        plan = api.post(
            f"/v1/clients/{client['id']}/care-plans",
            json={
                "authorized_tasks": RNG.sample(AUTHORIZED_TASKS, k=RNG.randint(3, 6)),
                "visit_frequency_rule": FREQUENCY_RULES[index % len(FREQUENCY_RULES)],
                "effective_start": (today - timedelta(days=30)).isoformat(),
                "default_service_type_code": (
                    "T1019" if payer == "medicaid_waiver" else "PRIVATE_HR"
                ),
            },
        )
        care_plan_ids.append(plan["id"])
    print(f"clients        {len(CLIENT_HOMES)}, each with an active care plan")

    window_start = today - timedelta(days=3)
    window_end = today + timedelta(days=10)
    visit_total = 0
    for plan_id in care_plan_ids:
        generated = api.post(
            f"/v1/care-plans/{plan_id}/generate-visits",
            json={
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "duration_minutes": 120,
            },
        )
        visit_total += len(generated)
    print(f"visits         {visit_total} generated for {window_start} .. {window_end}")

    # Assign most visits and leave the rest open, so the gap view and the suggestion ranker
    # both have something to work on. Assigning all of them would hide the feature the
    # scheduling board exists for.
    visits: list[dict[str, Any]] = []
    page_number = 1
    while True:
        page = api.get(
            "/v1/visits",
            params={
                "date_from": window_start.isoformat(),
                "date_to": window_end.isoformat(),
                "page": page_number,
                "page_size": 200,
            },
        )
        visits.extend(page["items"])
        if len(visits) >= page["page"]["total"]:
            break
        page_number += 1

    assigned = 0
    count = len(caregiver_ids)
    refusals: Counter[str] = Counter()
    for position, visit in enumerate(visits):
        if position % 7 == 3:
            continue
        # Rotate through caregivers so concurrent visits land on different people, except
        # today, which is offered to the caregiver who has a login first so the mobile app
        # opens on a real day of work. The server still refuses some of these — a
        # double-booking, an expired credential, a missing exclusion check. Those refusals
        # are the rules working, so the visit falls through to the next candidate and, if
        # nobody qualifies, stays open.
        rotation = [caregiver_ids[(position + i) % len(caregiver_ids)] for i in range(count)]
        if visit["scheduled_start"][:10] == today.isoformat():
            first = caregiver_ids[0]
            rotation = [first] + [c for c in rotation if c != first]
        for candidate in rotation:
            try:
                api.post(f"/v1/visits/{visit['id']}/assign", json={"caregiver_id": candidate})
            except RuntimeError as exc:
                refusals[_error_code(str(exc))] += 1
                continue
            assigned += 1
            break
    open_visits = len(visits) - assigned
    print(f"assignments    {assigned} assigned, {open_visits} left open")
    if refusals:
        detail = ", ".join(f"{code} x{count}" for code, count in refusals.most_common())
        print(f"               refused by the scheduling rules: {detail}")

    posting = api.post(
        "/v1/job-postings",
        json={
            "title": "Home Health Aide — Bay Ridge & Sunset Park",
            "description": (
                "Weekday morning and afternoon shifts with established clients. "
                "HHA certification required; CPR current. Travel within south Brooklyn."
            ),
            "required_credential_types": ["HHA", "CPR"],
            "service_state": "NY",
        },
    )
    # The pipeline only advances one stage at a time, so reaching "offer" means walking
    # through "screened" first. Four applicants stay at "applied" as the top of the funnel.
    journeys: list[list[str]] = (
        [["screened"]] * 6
        + [["screened", "offer"]] * 3
        + [["rejected"]] * 2
        + [["screened", "rejected"]]
        + [[]] * 4
    )
    for name, journey in zip(APPLICANT_NAMES, journeys, strict=True):
        handle = name.lower().replace(" ", ".").replace("ó", "o").replace("í", "i")
        applicant = api.post(
            "/v1/applicants",
            json={
                "job_posting_id": posting["id"],
                "source": RNG.choice(["indeed", "referral", "direct", "care.com"]),
                "full_name": name,
                "email": f"{handle}@example.com",
                "phone": f"+1718555{RNG.randint(1000, 9999)}",
                "claimed_credentials": RNG.sample(["HHA", "CPR", "CNA", "PCA"], k=2),
                "geo_lat": 40.62 + RNG.random() * 0.09,
                "geo_lng": -74.03 + RNG.random() * 0.09,
            },
        )
        for stage in journey:
            api.post(f"/v1/applicants/{applicant['id']}/stage", json={"stage": stage})
    print(f"applicants     {len(APPLICANT_NAMES)} across the pipeline")

    print()
    print("Sign in:")
    print(f"  admin app      {OWNER_EMAIL} / {DEMO_PASSWORD}")
    print(f"  caregiver app  {CAREGIVER_EMAIL} / {DEMO_PASSWORD}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        seed(args.base_url)
    except RuntimeError as exc:
        print(f"demo seed failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
