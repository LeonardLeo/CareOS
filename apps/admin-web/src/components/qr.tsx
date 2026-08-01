import QRCode from "qrcode";

/**
 * The enrolment QR code, rendered as inline SVG on the server.
 *
 * **Inline, not an image.** No second request, nothing cached by an intermediary, and — the
 * point that matters here — the `otpauth://` URI never becomes a URL that could end up in an
 * access log or a referrer header. It carries the shared secret; treating it as an asset would
 * be treating a credential as an asset.
 *
 * **Error correction stays at the default M.** A higher level survives more damage to a
 * printed code and makes the modules smaller on screen, which is the wrong trade for something
 * displayed for thirty seconds on a monitor and read from thirty centimetres away.
 *
 * The secret is still shown as text beside this. A QR is faster for the common case and no use
 * at all to someone enrolling a desktop password manager, or reading the screen with a
 * magnifier, or working from a phone that is the same device showing the page.
 */
export async function EnrolmentQr({ uri, label }: { uri: string; label: string }) {
  const svg = await QRCode.toString(uri, {
    type: "svg",
    margin: 1,
    // Fixed rather than inherited from the theme. A scanner reads a QR by contrast, and dark
    // mode inverting it to light-on-dark is the one theme change that stops it working on
    // several Android cameras.
    color: { dark: "#000000", light: "#ffffff" },
  });

  return (
    <div
      className="qr"
      role="img"
      aria-label={label}
      // The SVG is generated here from a URI we minted; nothing user-supplied reaches it.
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
