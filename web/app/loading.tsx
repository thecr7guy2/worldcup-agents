export default function Loading() {
  return (
    <div className="flex flex-col gap-8">
      <div className="skeleton h-56 w-full" />
      <div className="skeleton h-24 w-full" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="skeleton h-72" />
        ))}
      </div>
    </div>
  );
}
