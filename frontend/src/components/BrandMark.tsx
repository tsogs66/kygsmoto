/**
 * KYGSMOTO's mark: a drive sprocket with a K in the hub.
 *
 * A sprocket rather than a generic wheel or wrench because it is the part a
 * parts-and-service shop actually touches, and the K is for Kygs — the name
 * over the door.
 *
 * Ten teeth rather than twelve, and a heavy letter rather than a light one,
 * because both are what survives 16px in a browser tab: twelve fine teeth
 * blur into a fuzzy ring and a thin stem is the first thing to disappear.
 *
 * Drawn rather than imported so it inherits the app's tokens and stays crisp
 * at any size. The hub is filled with the bar colour so the letter reads on
 * light and dark alike — a favicon has no say in the tab it lands on.
 */
export default function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none"
         role="img" aria-label="KYGSMOTO">
      <g fill="var(--accent)">
        {TEETH.map((angle) => (
          <rect key={angle} x="27.75" y="0.5" width="8.5" height="9" rx="4.05"
                transform={`rotate(${angle} 32 32)`} />
        ))}
      </g>
      <circle cx="32" cy="32" r="23" fill="none" stroke="var(--accent)" strokeWidth="5.5" />
      <circle cx="32" cy="32" r="18" fill="var(--nav)" />
      <g fill="var(--ink)">
        <rect x="20.8" y="21" width="8.05" height="22" rx="1" />
        <path d="M40.9 21h-6.2l-7.4 9.6 3.6 4.7z" />
        <path d="M34.7 43h6.2l-7.6-10 -3.6 4.6z" />
      </g>
    </svg>
  )
}

/** Ten teeth, spaced by division rather than by eye. */
const TEETH = Array.from({ length: 10 }, (_, i) => (360 * i) / 10)
