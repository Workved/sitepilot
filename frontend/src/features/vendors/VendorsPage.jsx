import { useState } from "react";
import { Eye, Plus } from "lucide-react";
import { ConfirmModal, ManagementHeader, ManagementTable, Modal, Pill } from "../../components/ui";
import { vendorsApi } from "../../api/vendorsApi";
import { categories } from "../../utils/constants";
import { initials } from "../../utils/format";

function VendorCreateModal({ create, onClose }) {
  return <Modal title="Add Vendor" subtitle="Create a trade contact for task assignment" onClose={onClose}><form className="modal-form grid gap-3 [&_label]:grid [&_label]:gap-2 [&_label]:text-sm [&_label]:font-extrabold [&_label]:text-slate-700 [&_input]:min-h-11 [&_input]:w-full [&_input]:rounded-xl [&_input]:border [&_input]:border-slate-200 [&_input]:bg-white [&_input]:px-4 [&_input]:py-3 [&_input]:outline-none [&_select]:min-h-11 [&_select]:w-full [&_select]:rounded-xl [&_select]:border [&_select]:border-slate-200 [&_select]:bg-white [&_select]:px-4 [&_select]:py-3 [&_select]:outline-none [&_textarea]:min-h-24 [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-xl [&_textarea]:border [&_textarea]:border-slate-200 [&_textarea]:bg-white [&_textarea]:px-4 [&_textarea]:py-3 [&_textarea]:outline-none focus-within:[&_input]:border-blue-600 focus-within:[&_select]:border-blue-600 focus-within:[&_textarea]:border-blue-600 [&>button]:min-h-12 [&>button]:rounded-xl [&>button]:bg-blue-700 [&>button]:px-5 [&>button]:font-black [&>button]:text-white two-col grid-cols-2 max-[720px]:grid-cols-1" onSubmit={create}><label>Vendor Company<input name="name" placeholder="Enter vendor company" required /></label><label>Work Category<select name="category">{categories.map(c => <option key={c}>{c}</option>)}</select></label><label>Contact Person<input name="contact_person" placeholder="Enter contact person" required /></label><label>Phone Number<input name="phone" placeholder="Enter phone number" required /></label><label>WhatsApp<input name="whatsapp" placeholder="Optional" /></label><label>Notes<input name="notes" placeholder="Optional" /></label><button><Plus size={18} /> Add Vendor</button></form></Modal>;
}

function VendorModal({ vendor, action, onClose }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  async function save(e) { e.preventDefault(); await action(() => vendorsApi.update(vendor.id, Object.fromEntries(new FormData(e.currentTarget))), "Vendor updated"); onClose(); }
  async function remove() { const result = await action(() => vendorsApi.remove(vendor.id), "Vendor deleted"); if (result?.ok) { setConfirmDelete(false); onClose(); } }
  return <Modal title="Vendor Details" subtitle="Vendor contact and category" onClose={onClose}><div className="profile-hero mb-4 grid grid-cols-[auto_1fr_auto] items-center gap-4 rounded-2xl border border-blue-100 bg-gradient-to-br from-slate-50 to-blue-50 p-5 max-[620px]:grid-cols-[auto_1fr] [&_h3]:m-0 [&_h3]:text-2xl [&_h3]:font-black [&_p]:m-0 [&_p]:text-slate-500"><div className="avatar grid size-[46px] shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-blue-600 to-blue-900 font-black text-white shadow-[0_12px_24px_rgba(11,91,211,0.22)] large pastel">{initials(vendor.name)}</div><div><h3>{vendor.name}</h3><p>{vendor.contact_person} - {vendor.phone}</p></div><Pill>{vendor.category}</Pill></div><form className="modal-form grid gap-3 [&_label]:grid [&_label]:gap-2 [&_label]:text-sm [&_label]:font-extrabold [&_label]:text-slate-700 [&_input]:min-h-11 [&_input]:w-full [&_input]:rounded-xl [&_input]:border [&_input]:border-slate-200 [&_input]:bg-white [&_input]:px-4 [&_input]:py-3 [&_input]:outline-none [&_select]:min-h-11 [&_select]:w-full [&_select]:rounded-xl [&_select]:border [&_select]:border-slate-200 [&_select]:bg-white [&_select]:px-4 [&_select]:py-3 [&_select]:outline-none [&_textarea]:min-h-24 [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-xl [&_textarea]:border [&_textarea]:border-slate-200 [&_textarea]:bg-white [&_textarea]:px-4 [&_textarea]:py-3 [&_textarea]:outline-none focus-within:[&_input]:border-blue-600 focus-within:[&_select]:border-blue-600 focus-within:[&_textarea]:border-blue-600 [&>button]:min-h-12 [&>button]:rounded-xl [&>button]:bg-blue-700 [&>button]:px-5 [&>button]:font-black [&>button]:text-white two-col grid-cols-2 max-[720px]:grid-cols-1" onSubmit={save}><label>Vendor Company<input name="name" defaultValue={vendor.name} /></label><label>Category<select name="category" defaultValue={vendor.category}>{categories.map(c => <option key={c}>{c}</option>)}</select></label><label>Contact Person<input name="contact_person" defaultValue={vendor.contact_person} /></label><label>Phone<input name="phone" defaultValue={vendor.phone} /></label><label>WhatsApp<input name="whatsapp" defaultValue={vendor.whatsapp || ""} /></label><label>Notes<input name="notes" defaultValue={vendor.notes || ""} /></label><button>Save Vendor</button><button type="button" className="danger border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100" onClick={() => setConfirmDelete(true)}>Delete Vendor</button></form>{confirmDelete && <ConfirmModal title="Delete vendor?" message={`This will remove ${vendor.name}. Assigned tasks will become unassigned.`} confirmLabel="Delete Vendor" onClose={() => setConfirmDelete(false)} onConfirm={remove} />}</Modal>;
}

export function VendorsPage({ data, action }) {
  const [selected, setSelected] = useState(null);
  const [creating, setCreating] = useState(false);

  async function create(e) {
    e.preventDefault();

    const form = e.currentTarget;
    const payload = Object.fromEntries(new FormData(form));

    await action(() => vendorsApi.create(payload), "Vendor created");

    form.reset();
    setCreating(false);
  }

  return (
    <div className="stack grid gap-5">
      <ManagementHeader
        eyebrow="Vendor CRM"
        title="Vendors"
        subtitle="Manage vendor information and trade contacts"
        actionLabel="Add Vendor"
        actionIcon={<Plus size={18} />}
        onAction={() => setCreating(true)}
      />

      <ManagementTable
        countLabel="Total Vendors"
        count={data.vendors.length}
        searchPlaceholder="Search vendors?"
        tableClassName="vendor-table"
      >
            <colgroup>
              <col className="w-[28%]" />
              <col className="w-[15%]" />
              <col className="w-[20%]" />
              <col className="w-[15%]" />
              <col className="w-[14%]" />
              <col className="w-[8%]" />
            </colgroup>
            <thead>
              <tr className="data-row border-b border-slate-100 [&>td]:px-5 [&>td]:py-4 [&>td>small]:mt-1 [&>td>small]:block [&>td>small]:text-xs [&>td>small]:text-slate-500 table-head bg-slate-50 text-xs text-slate-500 [&>th]:px-5 [&>th]:py-4">
                <th scope="col">Vendor</th>
                <th scope="col">Category</th>
                <th scope="col">Contact Person</th>
                <th scope="col">Phone</th>
                <th scope="col">Status</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.vendors.map((vendor) => (
                <tr
                  key={vendor.id}
                  className="data-row border-b border-slate-100 [&>td]:px-5 [&>td]:py-4 [&>td>small]:mt-1 [&>td>small]:block [&>td>small]:text-xs [&>td>small]:text-slate-500"
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelected(vendor)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") setSelected(vendor);
                  }}
                >
                  <td data-label="Vendor"><b>{vendor.name}</b><small>{vendor.notes || "Vendor contact"}</small></td>
                  <td data-label="Category">{vendor.category}</td>
                  <td data-label="Contact Person">{vendor.contact_person}</td>
                  <td data-label="Phone">{vendor.phone}</td>
                  <td data-label="Status"><Pill tone="green">Active</Pill></td>
                  <td data-label="Actions">
                    <button
                      type="button"
                      className="kebab grid size-10 place-items-center rounded-xl bg-blue-50 p-0 text-blue-700"
                      aria-label={`Open ${vendor.name}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelected(vendor);
                      }}
                    >
                      <Eye size={20} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
      </ManagementTable>

      {creating && <VendorCreateModal create={create} onClose={() => setCreating(false)} />}
      {selected && <VendorModal vendor={selected} action={action} onClose={() => setSelected(null)} />}
    </div>
  );
}