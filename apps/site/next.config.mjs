/**
 * Static export.
 *
 * The public site has no session, no API call, and nothing personalised — so it has no reason
 * to need a running server. `output: "export"` makes it a directory of files, which is what
 * lets it sit on S3 behind CloudFront for pennies and stay up when the API does not. A
 * marketing page that goes down with the product is a marketing page that cannot tell anyone
 * the product is down.
 */
/** @type {import('next').NextConfig} */
export default {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
};
