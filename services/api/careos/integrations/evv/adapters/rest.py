"""Generic REST aggregator adapter.

`07_Integration_Specifications.md` Section 2 notes that aggregator integrations are
"commonly HTTPS API with JSON" but that the format varies by vendor. Rather than three
near-identical HTTP clients, the wire mapping is data: a `field_map` translating our
canonical six-element snapshot onto the vendor's field names, supplied per state from
`evv_aggregator_ref.connection_config`.

Adding a state whose aggregator speaks JSON over HTTPS is then a configuration row, not a
new class. States using batch/file submission need a genuinely different adapter — see
`batch_file.py`.

**The field maps shipped here are provisional.** They encode the structure, not verified
vendor contracts. Section 2 of that document requires every adapter to be validated against
the vendor's sandbox before any production visit data is transmitted, and the registry
enforces that with `evv_aggregator_ref.sandbox_validated`. Confirm the mapping against
current vendor documentation as part of that validation.
"""

from __future__ import annotations

from typing import Any

import httpx

from careos.integrations.evv.base import (
    EVVPayload,
    EVVTransmissionAdapter,
    TransmissionOutcome,
    TransmissionResult,
)

#: Transport-level conditions that warrant a retry rather than a compliance exception.
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class RestAggregatorAdapter(EVVTransmissionAdapter):
    """Submits the six elements as JSON to an aggregator's REST endpoint."""

    adapter_key = "rest_generic"
    aggregator_name = "Generic REST aggregator"

    #: Canonical snapshot key -> vendor field name. Overridden per vendor below.
    field_map: dict[str, str] = {}

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        sandbox: bool = True,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(config=config, sandbox=sandbox)
        self._client = client

    def _endpoint(self) -> str:
        key = "sandbox_url" if self.sandbox else "production_url"
        url = self.config.get(key)
        if not url:
            raise ValueError(
                f"Adapter {self.adapter_key} has no {key} configured for this state. "
                "Populate evv_aggregator_ref.connection_config."
            )
        return str(url)

    def build_body(self, payload: EVVPayload) -> dict[str, Any]:
        """Translate the canonical snapshot into the vendor's field names."""
        snapshot = payload.as_canonical_snapshot()
        mapping = {**self.field_map, **self.config.get("field_map", {})}
        body = {mapping.get(key, key): value for key, value in snapshot.items()}
        # Provider identifiers are per-agency contract values held in configuration, not
        # part of the federal element set.
        if provider_id := self.config.get("provider_id"):
            body[mapping.get("provider_id", "provider_id")] = provider_id
        body["visit_id"] = str(payload.visit_id)
        return body

    async def submit(self, payload: EVVPayload) -> TransmissionResult:
        payload.validate()
        body = self.build_body(payload)
        client = self._client or httpx.AsyncClient(timeout=30.0)
        should_close = self._client is None
        try:
            response = await client.post(
                self._endpoint(),
                json=body,
                headers=self.config.get("headers", {}),
            )
        except httpx.HTTPError as exc:
            # Network-level failure: the aggregator may or may not have received it. The
            # caller retries under the same Idempotency-Key, so a duplicate is not created.
            return TransmissionResult(
                outcome=TransmissionOutcome.transient_failure,
                error_message=str(exc),
            )
        finally:
            if should_close:
                await client.aclose()

        return self.interpret_response(response)

    def interpret_response(self, response: httpx.Response) -> TransmissionResult:
        try:
            raw = response.json()
        except ValueError:
            raw = {"body": response.text[:2000]}

        if response.status_code in _RETRYABLE_STATUS:
            return TransmissionResult(
                outcome=TransmissionOutcome.transient_failure,
                raw_response=raw,
                error_message=f"Aggregator returned {response.status_code}",
            )
        if response.is_success:
            # Acceptance and mere receipt are different states. Only an explicit
            # acknowledgement makes the visit compliant, so anything ambiguous is recorded
            # as `submitted` and left for the status poll to resolve.
            ack_field = self.config.get("ack_field", "status")
            ack_values = set(self.config.get("ack_values", ["accepted", "acknowledged"]))
            if str(raw.get(ack_field, "")).lower() in ack_values:
                outcome = TransmissionOutcome.accepted
            else:
                outcome = TransmissionOutcome.submitted
            return TransmissionResult(
                outcome=outcome,
                aggregator_reference=raw.get(self.config.get("reference_field", "transaction_id")),
                raw_response=raw,
            )
        return TransmissionResult(
            outcome=TransmissionOutcome.rejected,
            raw_response=raw,
            error_message=f"Aggregator rejected the record ({response.status_code})",
        )


class SandataAdapter(RestAggregatorAdapter):
    adapter_key = "sandata"
    aggregator_name = "Sandata"
    field_map = {
        "type_of_service": "ServiceType",
        "individual_receiving_service": "Client",
        "date_of_service": "VisitDate",
        "location_of_service": "VisitLocation",
        "individual_providing_service": "Employee",
        "service_begin_time": "VisitTimeIn",
        "service_end_time": "VisitTimeOut",
        "provider_id": "ProviderIdentification",
    }


class HHAeXchangeAdapter(RestAggregatorAdapter):
    adapter_key = "hhaexchange"
    aggregator_name = "HHAeXchange"
    field_map = {
        "type_of_service": "serviceCode",
        "individual_receiving_service": "patient",
        "date_of_service": "visitDate",
        "location_of_service": "location",
        "individual_providing_service": "caregiver",
        "service_begin_time": "startTime",
        "service_end_time": "endTime",
        "provider_id": "providerId",
    }


class TellusAdapter(RestAggregatorAdapter):
    adapter_key = "tellus"
    aggregator_name = "Tellus"
    field_map = {
        "type_of_service": "serviceType",
        "individual_receiving_service": "recipient",
        "date_of_service": "serviceDate",
        "location_of_service": "serviceLocation",
        "individual_providing_service": "provider",
        "service_begin_time": "timeIn",
        "service_end_time": "timeOut",
        "provider_id": "providerNumber",
    }
