/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The admin app never talks to the API from the browser directly. Requests go through
  // Next route handlers so the access token stays in an httpOnly cookie and is never
  // readable by page JavaScript — see src/lib/session.ts.
  env: {
    CAREOS_API_URL: process.env.CAREOS_API_URL ?? "http://localhost:8000",
  },
};
export default nextConfig;
