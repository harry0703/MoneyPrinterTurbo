import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MoneyPrinterTurbo",
  description: "Create polished short-form videos from one idea.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
