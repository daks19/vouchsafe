import React from 'react';

// Big number on a tinted tile. Adapted from IPO SHERPA's ui/StatTile.jsx.
const TONES = {
  success: 'bg-emerald-50 border-emerald-100 text-emerald-600',
  warning: 'bg-amber-50 border-amber-100 text-amber-500',
  danger:  'bg-red-50 border-red-100 text-red-500',
  neutral: 'bg-gray-50 border-gray-100 text-gray-500',
  accent:  'bg-accent-50 border-accent-100 text-accent-600',
};

export default function StatTile({ value, label, tone = 'neutral', icon: Icon }) {
  const classes = TONES[tone];
  return (
    <div className={`rounded-xl py-3 px-2 border text-center ${classes}`}>
      {Icon && <Icon className="w-4 h-4 mx-auto mb-1 opacity-80" />}
      <span className="text-2xl font-display font-bold block">{value}</span>
      <span className="text-[9.5px] font-bold uppercase tracking-wide opacity-70">{label}</span>
    </div>
  );
}
