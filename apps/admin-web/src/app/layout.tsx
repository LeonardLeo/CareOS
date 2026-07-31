import type { Metadata } from "next";
import { getLocale } from "@/lib/locale";
import "@/styles/tokens.css";
import "@/styles/app.css";

export const metadata: Metadata = {
  title: "CareOS — Agency Admin",
  description: "AI-native operating system for home-based care agencies",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // `lang` has to be the language actually rendered, not a constant. A screen reader chooses
  // its voice and pronunciation rules from this attribute, so Spanish text under `lang="en"`
  // is read aloud with English phonetics — intelligible to nobody. It also drives hyphenation
  // and the quotation marks a browser inserts.
  const locale = await getLocale();
  return (
    <html lang={locale}>
      <body>{children}</body>
    </html>
  );
}
