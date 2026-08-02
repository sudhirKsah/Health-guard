import Link from "next/link";

export default function OfflinePage() {
  return (
    <main className="offline-page">
      <div className="offline-mark" aria-hidden>H</div>
      <p className="eyebrow">Health Guard</p>
      <h1>You’re offline.</h1>
      <p>
        Your private care information and live payment status need an internet connection. Reconnect,
        then reopen Health Guard to see the latest supplies and transactions.
      </p>
      <Link href="/dashboard">Try again</Link>
    </main>
  );
}
