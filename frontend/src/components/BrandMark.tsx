/**
 * KYGSMOTO's mark: a drive sprocket with a K in the hub.
 *
 * A sprocket rather than a generic wheel or wrench because it is the part a
 * parts-and-service shop actually touches, and because the toothed silhouette
 * stays recognisable at 16px in a browser tab where finer detail would blur.
 * The K is for Kygs — the name over the door.
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
        {TEETH.map((rotate, i) => (
          <rect key={i} x="28.40" y="1.00" width="7.2" height="9" rx="3.4"
                transform={`rotate(${rotate} 32 32)`} />
        ))}
      </g>
      <circle cx="32" cy="32" r="23" fill="none" stroke="var(--accent)" strokeWidth="5.5" />
      <circle cx="32" cy="32" r="17.5" fill="var(--nav)" />
      <g fill="var(--ink)">
        <rect x="21.5" y="21" width="5.4" height="22" rx="1" />
        <path d="M40.9 21h-6.2l-7.4 9.6 3.1 4.1z" />
        <path d="M34.7 43h6.2l-7.6-10 -3.1 4z" />
      </g>
    </svg>
  )
}

/** Twelve teeth, spaced by division rather than by eye. */
const TEETH = Array.from({ length: 12 }, (_, i) => (360 * i) / 12)
