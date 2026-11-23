import { Pill } from "../../../components/ui";

export const STATUS_META = {
  scheduled: { label: "Scheduled", tone: "blue" },
  sent: { label: "Sent", tone: "green" },
  partially_failed: { label: "Partly failed", tone: "orange" },
  failed: { label: "Failed", tone: "red" },
  pending: { label: "Pending", tone: "gray" },
  skipped_no_contact: { label: "No contact", tone: "orange" },
};

export function StatusChip({ status, className }) {
  const meta = STATUS_META[status] || { label: status, tone: "gray" };
  return <Pill tone={meta.tone} className={className}>{meta.label}</Pill>;
}
