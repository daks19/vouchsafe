import React from 'react';

// The case's audit trail, newest last. Pattern from IPO SHERPA's AuditTrail.jsx (kind + summary + time).
export default function Timeline({ items }) {
  return (
    <ol className="space-y-2 text-xs">
      {items.map((e, i) => (
        <li key={i} className="flex gap-3">
          <time className="font-mono text-gray-400 shrink-0">{e.at.slice(11, 19)}</time>
          <span className="font-mono font-semibold text-accent-700 shrink-0 w-36">{e.kind}</span>
          <span className="text-gray-600 whitespace-pre-line line-clamp-3">{e.summary}</span>
        </li>
      ))}
    </ol>
  );
}
