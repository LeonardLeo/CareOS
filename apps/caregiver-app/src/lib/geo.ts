/**
 * Location capture for EVV.
 *
 * `09_UX_Design_and_User_Flows.md` Flow B step 2 is specific that the no-GPS fallback "must be
 * just as usable, not a degraded afterthought", and `02_Product_Requirements_Document.md`
 * US-1.4.3 names telephony and manual exception as compliant capture methods in their own
 * right. So this module never blocks a clock-in on getting a fix: it returns what it got and
 * lets the caller proceed either way.
 *
 * The timeout is short on purpose. A caregiver standing in a doorway will not wait 30 seconds
 * for a satellite lock, and a clock-in delayed past the visit's start time is a compliance
 * problem of its own. Better to record `manual_exception` with an honest reason at 09:00 than
 * `mobile_gps` at 09:01 after a spinner.
 */

import type { CaptureMethod, GeoPoint } from "./outbox";

const FIX_TIMEOUT_MS = 8_000;

export interface LocationCapture {
  geo: GeoPoint | null;
  captureMethod: CaptureMethod;
  /** Present when no fix was obtained. Travels to the agency as the EVV exception reason. */
  exceptionReason: string | null;
  accuracyMetres: number | null;
}

/** Reasons a fix failed, in words an agency reconciling an exception can act on. */
function describe(error: GeolocationPositionError): string {
  switch (error.code) {
    case error.PERMISSION_DENIED:
      return "Location permission denied on device";
    case error.POSITION_UNAVAILABLE:
      return "No location fix available (indoors or no signal)";
    case error.TIMEOUT:
      return "Location lookup timed out";
    default:
      return error.message || "Location unavailable";
  }
}

export async function captureLocation(): Promise<LocationCapture> {
  if (typeof navigator === "undefined" || !navigator.geolocation) {
    return {
      geo: null,
      captureMethod: "manual_exception",
      exceptionReason: "Device has no location services",
      accuracyMetres: null,
    };
  }

  return new Promise<LocationCapture>((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (position) =>
        resolve({
          geo: { lat: position.coords.latitude, lng: position.coords.longitude },
          captureMethod: "mobile_gps",
          exceptionReason: null,
          accuracyMetres:
            typeof position.coords.accuracy === "number" ? position.coords.accuracy : null,
        }),
      (error) =>
        resolve({
          geo: null,
          captureMethod: "manual_exception",
          exceptionReason: describe(error),
          accuracyMetres: null,
        }),
      { enableHighAccuracy: true, timeout: FIX_TIMEOUT_MS, maximumAge: 60_000 },
    );
  });
}
