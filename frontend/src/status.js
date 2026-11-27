// Plain labels for case statuses and workflows, shared by the queue and the detail panel.
export const STATUS = {
  waiting_approval: { label: 'Waiting for approval', variant: 'warning' },
  waiting_reply:    { label: 'Waiting for reply',    variant: 'info' },
  waiting_supplier: { label: 'Waiting for supplier', variant: 'info' },
  waiting_ca:       { label: 'Waiting for the CA',   variant: 'indigo' },
  needs_retry:      { label: 'Needs a retry',        variant: 'danger' },
  resolved:         { label: 'Resolved',             variant: 'success' },
  declined:         { label: 'Declined',             variant: 'neutral' },
};

export const WORKFLOW = {
  W1: { label: 'W1 Confirm delivery', issue: 'On the GST portal, but no bill in the books' },
  W2: { label: 'W2 Supplier fix',     issue: 'Supplier has not reported the bill correctly' },
  W3: { label: 'W3 Keep evidence',    issue: "Supplier's registration cancelled from a past date" },
};
