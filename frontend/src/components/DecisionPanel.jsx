import React, { useState } from 'react';
import { Gavel } from 'lucide-react';
import { CHOICE, DOCUMENT } from '../status';

// The CA's decision on a handed-over case. Options come from the server (from the actual IMS record).
export default function DecisionPanel({ waiting, busy, onDecide }) {
  const [note, setNote] = useState('');
  const [reason, setReason] = useState('');
  const [na, setNa] = useState([]);
  const toggle = (k) => setNa((x) => (x.includes(k) ? x.filter((y) => y !== k) : [...x, k]));
  const decide = (choice) =>
    onDecide({ choice, note, reason, not_applicable: na, sha256: waiting.sha256 });

  return (
    <div className="rounded-xl border border-indigo-200 bg-indigo-50/50 p-4 space-y-3">
      <p className="flex items-center gap-2 font-semibold text-indigo-900"><Gavel className="w-4 h-4" />Your decision (CA)</p>
      <p className="text-sm text-gray-700 whitespace-pre-line">{waiting.text}</p>
      {waiting.record
        ? <p className="text-xs text-gray-500">IMS record {waiting.record.key} ({waiting.record.doc_type}), now: {waiting.record.action} (SIMULATED)</p>
        : waiting.missing.length === 0 && <p className="text-xs text-gray-500">No IMS record for this bill: the supplier has not reported it, so there is nothing to accept or reject yet.</p>}
      {waiting.missing.length > 0 && (
        <fieldset className="text-sm">
          <legend className="text-xs font-semibold text-gray-600 mb-1">Missing documents. Tick any that do not apply to this purchase:</legend>
          {waiting.missing.map((k) => (
            <label key={k} className="flex items-center gap-2">
              <input type="checkbox" checked={na.includes(k)} onChange={() => toggle(k)} />
              {DOCUMENT[k] ?? k}: not applicable
            </label>
          ))}
        </fieldset>
      )}
      <label className="block text-xs font-semibold text-gray-600">Note (optional)
        <input className="form-input-base mt-1" value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      {waiting.options.includes('closed') && (
        <label className="block text-xs font-semibold text-gray-600">Reason (needed to close)
          <input className="form-input-base mt-1" value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      )}
      <div className="flex flex-wrap gap-2">
        {waiting.options.map((c) => (
          <button key={c} type="button" disabled={busy} onClick={() => decide(c)}
                  className={`rounded-lg px-3 py-2 text-sm font-semibold border disabled:opacity-50 ${
                    c === 'reject' ? 'border-red-300 text-red-700 bg-white hover:bg-red-50'
                    : c === 'closed' ? 'border-gray-300 text-gray-700 bg-white hover:bg-gray-50'
                    : 'border-indigo-300 text-indigo-800 bg-white hover:bg-indigo-50'}`}>
            {CHOICE[c] ?? c}
          </button>
        ))}
      </div>
    </div>
  );
}
