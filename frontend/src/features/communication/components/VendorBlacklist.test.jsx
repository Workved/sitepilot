import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BlacklistBanner, BlacklistModal, BlacklistPill, canBlacklist, canUnblacklist, isBlocked } from "./VendorBlacklist";
import { VendorRow } from "./CommunicationDirectory";

const listed = { id: "v1", name: "Acme Interiors", engagement_type: "main", blacklisted: false, blocked_by_parent: false, categories: [] };
const blacklisted = { ...listed, blacklisted: true, blacklist_reason: "Left site mid-job", blacklisted_by_name: "Shikhar", blacklisted_at: "2026-11-15T10:00:00Z" };
const blockedSub = { ...listed, id: "v2", name: "Acme Sub", engagement_type: "sub_vendor", blocked_by_parent: true };

describe("blacklist status display", () => {
  it("shows nothing for a normal vendor - no 'Active' anywhere", () => {
    const { container } = render(<BlacklistPill vendor={listed}/>);
    expect(container).toBeEmptyDOMElement();
    expect(isBlocked(listed)).toBe(false);
  });

  it("shows Blacklisted, and the main-vendor block for a sub-vendor", () => {
    render(<><BlacklistPill vendor={blacklisted}/><BlacklistPill vendor={blockedSub}/></>);
    expect(screen.getByText("Blacklisted")).toBeInTheDocument();
    expect(screen.getByText("Main vendor blacklisted")).toBeInTheDocument();
    expect(isBlocked(blockedSub)).toBe(true);
  });

  it("banner shows who, when and why", () => {
    render(<BlacklistBanner vendor={blacklisted}/>);
    expect(screen.getByText(/Blacklisted by Shikhar on 15 Nov 2026/)).toBeInTheDocument();
    expect(screen.getByText("Reason: Left site mid-job")).toBeInTheDocument();
  });

  it("vendor list row has no status pill for a normal vendor", () => {
    render(<VendorRow vendor={listed} projectCount={2} onSelect={vi.fn()}/>);
    expect(screen.queryByText(/^Active$|On hold|Inactive/)).toBeNull();
  });
});

describe("who can blacklist", () => {
  it("admins, PMs and supervisors blacklist; only admins remove", () => {
    for (const role of ["super_admin", "admin", "project_manager", "supervisor"]) expect(canBlacklist({ role })).toBe(true);
    expect(canBlacklist({ role: "internal_employee" })).toBe(false);
    expect(canUnblacklist({ role: "admin" })).toBe(true);
    expect(canUnblacklist({ role: "supervisor" })).toBe(false);
    expect(canUnblacklist({ role: "project_manager" })).toBe(false);
  });

  it("row menu offers Blacklist to a supervisor and Remove only to an admin", () => {
    const onBlacklist = vi.fn();
    const { unmount } = render(<VendorRow vendor={listed} projectCount={0} onSelect={vi.fn()} canBlacklist onBlacklist={onBlacklist}/>);
    fireEvent.click(screen.getByRole("button", { name: /Vendor row actions/i }));
    fireEvent.click(screen.getByRole("button", { name: "Blacklist vendor" }));
    expect(onBlacklist).toHaveBeenCalled();
    unmount();

    // With nothing this user may do to the row, there is no empty menu at all.
    render(<VendorRow vendor={blacklisted} projectCount={0} onSelect={vi.fn()} canBlacklist/>);
    expect(screen.queryByRole("button", { name: /Vendor row actions/i })).toBeNull();
    expect(screen.queryByRole("button", { name: "Blacklist vendor" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove from blacklist" })).toBeNull();
  });
});

describe("BlacklistModal", () => {
  it("needs a reason before blacklisting and explains the effects", () => {
    const onSubmit = vi.fn();
    render(<BlacklistModal vendor={listed} mode="blacklist" projectCount={2} subVendorCount={1} onClose={vi.fn()} onSubmit={onSubmit}/>);
    expect(screen.getByText(/removed from 2 current projects/)).toBeInTheDocument();
    expect(screen.getByText(/1 sub-vendor is blocked too/)).toBeInTheDocument();
    expect(screen.getByText(/won't be sent any message/)).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "Blacklist vendor" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reason for blacklisting"), { target: { value: "  Repeated delays  " } });
    fireEvent.click(submit);
    expect(onSubmit).toHaveBeenCalledWith("Repeated delays");
  });

  it("remove mode asks why and says nothing is restored", () => {
    const onSubmit = vi.fn();
    render(<BlacklistModal vendor={blacklisted} mode="remove" onClose={vi.fn()} onSubmit={onSubmit}/>);
    expect(screen.getByText(/are not restored/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Why remove them from the blacklist?"), { target: { value: "Issue resolved" } });
    fireEvent.click(screen.getByRole("button", { name: "Remove from blacklist" }));
    expect(onSubmit).toHaveBeenCalledWith("Issue resolved");
  });
});
