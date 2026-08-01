export function BrandMark({
  className = "h-6 w-6",
}: {
  className?: string;
}) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="vt-mark-grad" x1="0" y1="32" x2="32" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#EA580C" />
          <stop offset="1" stopColor="#F7A316" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="7.5" fill="url(#vt-mark-grad)" />
      {/* Three ascending candlesticks. */}
      <line x1="9.5" y1="14" x2="9.5" y2="24.5" stroke="#ffffff" strokeOpacity="0.75" strokeWidth="1.8" strokeLinecap="round" />
      <rect x="7.5" y="16" width="4" height="6" rx="1" fill="#ffffff" />
      <line x1="16" y1="9.5" x2="16" y2="21.5" stroke="#ffffff" strokeOpacity="0.75" strokeWidth="1.8" strokeLinecap="round" />
      <rect x="14" y="11.5" width="4" height="7" rx="1" fill="#ffffff" />
      <line x1="22.5" y1="5.5" x2="22.5" y2="18" stroke="#ffffff" strokeOpacity="0.75" strokeWidth="1.8" strokeLinecap="round" />
      <rect x="20.5" y="7.5" width="4" height="7.5" rx="1" fill="#ffffff" />
    </svg>
  );
}
