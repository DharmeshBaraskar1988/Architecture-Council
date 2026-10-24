import type { NextConfig } from "next";

const config: NextConfig = {
  // Runs are read from ../data/runs on the server; nothing is bundled or sent elsewhere.
  poweredByHeader: false,
};

export default config;
