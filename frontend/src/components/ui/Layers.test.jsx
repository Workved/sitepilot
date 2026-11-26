import { fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Popover } from "./Popover";
import { Tooltip } from "./Tooltip";

function Menu({ onPick = () => {} }) {
  const [open, setOpen] = useState(false);
  const anchor = useRef(null);
  return <div data-testid="card" style={{ overflow: "hidden" }}>
    <div ref={anchor}><button type="button" onClick={() => setOpen(value => !value)}>Actions</button></div>
    <Popover anchorRef={anchor} open={open} onClose={() => setOpen(false)} role="menu">
      <button type="button" role="menuitem" onClick={() => { onPick(); setOpen(false); }}>Delete</button>
    </Popover>
    <p>Outside</p>
  </div>;
}

describe("Popover", () => {
  it("renders in <body>, outside the card that opened it, so the card can't clip or cover it", () => {
    render(<Menu/>);
    fireEvent.click(screen.getByRole("button", { name: "Actions" }));
    const menu = screen.getByRole("menu");
    expect(screen.getByTestId("card").contains(menu)).toBe(false);
    expect(menu.parentElement).toBe(document.body);
    expect(menu.className).toContain("z-[80]");
  });

  it("lets a click inside run before closing, and closes on an outside click or Escape", () => {
    const onPick = vi.fn();
    render(<Menu onPick={onPick}/>);
    const toggle = screen.getByRole("button", { name: "Actions" });
    fireEvent.click(toggle);
    const item = screen.getByRole("menuitem", { name: "Delete" });
    fireEvent.mouseDown(item);
    fireEvent.click(item);
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).toBeNull();

    fireEvent.click(toggle);
    fireEvent.mouseDown(screen.getByText("Outside"));
    expect(screen.queryByRole("menu")).toBeNull();

    fireEvent.click(toggle);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("toggles closed from its own trigger instead of reopening", () => {
    render(<Menu/>);
    const toggle = screen.getByRole("button", { name: "Actions" });
    fireEvent.click(toggle);
    fireEvent.mouseDown(toggle);
    fireEvent.click(toggle);
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("Tooltip", () => {
  it("shows in <body> on hover and focus, and hides on leave", () => {
    render(<nav style={{ position: "sticky" }}><Tooltip label="Templates"><button type="button" aria-label="Templates">T</button></Tooltip></nav>);
    const button = screen.getByRole("button", { name: "Templates" });
    fireEvent.mouseEnter(button.parentElement);
    expect(screen.getByRole("tooltip").parentElement).toBe(document.body);
    fireEvent.mouseLeave(button.parentElement);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.focus(button);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Templates");
  });
});
