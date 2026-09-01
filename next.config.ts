import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  typescript: {
    ignoreBuildErrors: true,
  },
  reactStrictMode: false,
  // Dev server cross-origin protection (Next 16): chunk/HMR requests whose
  // Origin/Referer host differs from the canonical one are blocked with 403,
  // which silently breaks hydration when the app is opened via 127.0.0.1
  // (or a LAN IP) instead of localhost. Allow the common local hostnames.
  allowedDevOrigins: ["localhost", "127.0.0.1"],
};

export default nextConfig;
