import type { Metadata } from "next";
import "@/styles/tokens.css";
import "@/styles/app.css";

export const metadata: Metadata = {
  title: "CareOS — Agency Admin",
  description: "AI-native operating system for home-based care agencies",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
