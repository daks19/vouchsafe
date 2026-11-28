import React from 'react';

// Readiness for the period: cases resolved out of all cases. Arc drawing adapted from IPO SHERPA's
// ComplianceScoreMeter.jsx. A case handed to the CA or declined is not resolved.
const R = 52, CX = 70, CY = 70, C = 2 * Math.PI * R, ARC = C * (240 / 360);

export default function Readiness({ resolved, total }) {
  const pct = total ? resolved / total : 0;
  const color = pct === 1 ? '#10b981' : pct >= 0.5 ? '#f59e0b' : '#3A7CA5';
  return (
    <div className="card p-4 flex items-center gap-4">
      <svg width="140" height="120" viewBox="0 0 140 120" role="img" aria-label={`${resolved} of ${total} cases resolved`}>
        <circle cx={CX} cy={CY} r={R} fill="none" stroke="#f1f5f9" strokeWidth="11" strokeLinecap="round"
                strokeDasharray={`${ARC} ${C - ARC}`} transform={`rotate(150 ${CX} ${CY})`} />
        <circle cx={CX} cy={CY} r={R} fill="none" stroke={color} strokeWidth="11" strokeLinecap="round"
                strokeDasharray={`${ARC} ${C - ARC}`} strokeDashoffset={ARC * (1 - pct)}
                transform={`rotate(150 ${CX} ${CY})`} style={{ transition: 'stroke-dashoffset 0.8s ease' }} />
        <text x={CX} y={CY - 4} textAnchor="middle" fontSize="28" fontWeight="800" fill={color}>{resolved}</text>
        <text x={CX} y={CY + 18} textAnchor="middle" fontSize="11" fill="#64748b">of {total}</text>
      </svg>
      <div>
        <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-400">Ready for the period</p>
        <p className="text-lg font-display font-bold text-gray-800">{resolved} of {total} cases resolved</p>
        <p className="text-xs text-gray-500 mt-1">Vouchsafe prepares. A person approves and files.</p>
      </div>
    </div>
  );
}
