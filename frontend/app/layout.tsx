import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Council Replay",
  description: "Replay of an Architecture Council run: facts, proposals, fact checks, challenges, votes and the decision.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@500;700&family=JetBrains+Mono:wght@400;600&family=Schibsted+Grotesk:wght@400;600&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
