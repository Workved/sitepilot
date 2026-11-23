// The SiteOps mark: two ink slabs and a blue block, read as a floor plan.
export function BrandMark({ className = "size-9" }) {
  return <svg viewBox="0 0 34 34" className={className} role="img" aria-label="SiteOps">
    <rect x="3" y="18" width="12" height="13" rx="3" fill="#15171a" />
    <rect x="19" y="3" width="12" height="28" rx="3" fill="#15171a" />
    <rect x="3" y="3" width="12" height="11" rx="3" fill="#2f5fe0" />
  </svg>;
}
