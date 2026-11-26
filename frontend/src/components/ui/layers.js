/*
 * The app's stacking order, lowest first. Anything that floats over the page
 * renders through a portal into <body> and takes its z-index from here, so it
 * can never end up behind the page, or be cut off by, the card it opened from.
 *
 * Why a portal and not just a bigger z-index: a z-index only competes with
 * siblings in the same stacking context. The sidebar is `sticky`, the top bar
 * blurs its backdrop, cards scroll or hide their overflow - each of those
 * traps whatever is drawn inside it, whatever its z-index.
 */
export const LAYER = {
  drawer: "z-50",     // side drawers and modals (and their backdrops at z-40)
  stacked: "z-[70]",  // a drawer opened from inside another drawer
  popover: "z-[80]",  // menus, pickers and popovers - also over drawers and modals
  tooltip: "z-[90]",
  toast: "z-[100]",
};
