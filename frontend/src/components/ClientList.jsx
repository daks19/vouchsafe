import React from 'react';
import { Store } from 'lucide-react';

export default function ClientList({ clients }) {
  return (
    <nav className="card p-4 space-y-2" aria-label="Clients">
      <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-400">Clients</p>
      {clients.map((c) => (
        <div
          key={c.name}
          aria-current={c.active ? 'true' : undefined}
          className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${
            c.active ? 'bg-accent-50 border border-accent-200 text-accent-800 font-semibold' : 'text-gray-400'
          }`}
        >
          <Store className="w-4 h-4 shrink-0" />
          <span className="truncate">{c.name}</span>
        </div>
      ))}
    </nav>
  );
}
