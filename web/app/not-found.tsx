import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-[50dvh] flex-col items-center justify-center text-center">
      <span className="font-display text-7xl font-extrabold text-volt">404</span>
      <h1 className="mt-4 font-display text-2xl font-bold text-ink">Offside</h1>
      <p className="mt-2 max-w-[40ch] text-sm text-muted">
        That page is not on the pitch. Head back to the Arena.
      </p>
      <Link
        href="/"
        className="mt-6 inline-flex items-center border-2 border-ink bg-volt px-5 py-2.5 text-sm font-bold uppercase text-surface shadow-[4px_4px_0_var(--color-ink)] transition-transform hover:-translate-y-0.5"
      >
        Back to the Arena
      </Link>
    </div>
  );
}
