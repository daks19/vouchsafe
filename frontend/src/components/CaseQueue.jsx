import React from 'react';
import Badge from './ui/Badge';
import { STATUS, WORKFLOW } from '../status';

export default function CaseQueue({ cases, selectedId, onSelect }) {
  return (
    <div className="card overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-[10px] uppercase tracking-wider text-gray-400">
          <tr>
            <th className="text-left px-4 py-2 font-bold">Workflow</th>
            <th className="text-left px-4 py-2 font-bold">Supplier and invoice</th>
            <th className="text-left px-4 py-2 font-bold">Issue</th>
            <th className="text-left px-4 py-2 font-bold">Status</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => {
            const st = STATUS[c.status] ?? { label: c.status, variant: 'neutral' };
            const selected = c.case_id === selectedId;
            return (
              <tr
                key={c.case_id}
                onClick={() => onSelect(c.case_id)}
                onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onSelect(c.case_id)}
                tabIndex={0}
                aria-selected={selected}
                className={`border-t border-gray-100 cursor-pointer ${selected ? 'bg-accent-50' : 'hover:bg-gray-50'}`}
              >
                <td className="px-4 py-3"><Badge variant="accent" size="xs">{WORKFLOW[c.workflow]?.label ?? c.workflow}</Badge></td>
                <td className="px-4 py-3 font-semibold text-gray-800">{c.title}</td>
                <td className="px-4 py-3 text-gray-600">{WORKFLOW[c.workflow]?.issue}</td>
                <td className="px-4 py-3"><Badge variant={st.variant} size="xs" dot>{st.label}</Badge></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
