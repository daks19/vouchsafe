import React from 'react';
import { Send, Mic, FileCheck2, RotateCw } from 'lucide-react';
import Badge from './ui/Badge';
import Timeline from './Timeline';
import DecisionPanel from './DecisionPanel';
import { DOCUMENT, LANGUAGE, STATUS, WORKFLOW } from '../status';

const H = ({ children }) => <h3 className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-400 mb-2">{children}</h3>;

function Approval({ w, busy, onApprove }) {
  const both = w.text_en && w.text_en !== w.text;
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 space-y-3">
      <p className="text-sm font-semibold text-amber-900">
        {w.action === 'message' ? `Message to ${w.to}` : w.action === 'ca_handoff' ? 'Hand the case to the CA' : `Action: ${w.to}`}
        <span className="font-normal text-amber-800"> · {LANGUAGE[w.lang] ?? w.lang}</span>
      </p>
      <div className={`grid gap-3 ${both ? 'grid-cols-2' : ''}`}>
        <p className="text-sm text-gray-800 whitespace-pre-line bg-white rounded-lg p-3 border" lang={w.lang.slice(0, 2)}>{w.text}</p>
        {both && <p className="text-sm text-gray-600 whitespace-pre-line bg-white rounded-lg p-3 border" lang="en"><span className="block text-[10px] font-bold text-gray-400 mb-1">ENGLISH</span>{w.text_en}</p>}
      </div>
      {w.note && <p className="text-xs text-amber-800">{w.note}</p>}
      {w.action === 'ca_handoff' && <p className="text-xs text-amber-800">Next, the CA chooses what to do in IMS (for example Keep Pending).</p>}
      <div className="flex gap-2">
        <button type="button" disabled={busy} onClick={() => onApprove(true, w.sha256)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-600 px-4 py-2 text-sm font-semibold text-white hover:bg-accent-700 disabled:opacity-50">
          <Send className="w-4 h-4" />{w.approver === 'CA' ? 'Approve as CA' : w.action === 'ca_handoff' ? 'Send to the CA (owner approves)' : 'Approve as owner (demo)'}
        </button>
        <button type="button" disabled={busy} onClick={() => onApprove(false, w.sha256)}
                className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50">Decline</button>
      </div>
    </div>
  );
}

export default function CaseDetail({ detail: d, busy, onApprove, onDecide, onRetry }) {
  const f = d.facts, w = d.waiting, st = STATUS[d.status] ?? { label: d.status, variant: 'neutral' };
  const replies = d.timeline.filter((e) => e.kind === 'shop.replied');
  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-center gap-2 mb-1">
          <Badge variant="accent" size="xs">{WORKFLOW[d.workflow]?.label}</Badge>
          <Badge variant={st.variant} size="xs" dot>{st.label}</Badge>
        </div>
        <h2 className="text-xl font-display font-bold text-gray-900">{f.supplier ?? f.ctin} {f.invoice_no ?? ''}</h2>
        <p className="text-sm text-gray-600">{WORKFLOW[d.workflow]?.issue}{f.invoice_date ? ` · invoice dated ${f.invoice_date.split('-').reverse().join('-')}` : ''}</p>
        {d.outcome && <p className="mt-2 text-sm font-semibold text-emerald-700">{d.outcome}</p>}
      </div>

      <div>
        <H>Rules applied</H>
        <ul className="space-y-1 text-xs text-gray-600">
          {d.rules.map((r) => <li key={r.id}><span className="font-mono text-accent-700">{r.id}</span> {r.title}<br /><span className="text-gray-400">{r.citations[0]}</span></li>)}
        </ul>
      </div>

      {w?.type === 'approval' && <Approval w={w} busy={busy} onApprove={onApprove} />}
      {w?.type === 'ca_decision' && <DecisionPanel key={w.sha256} waiting={w} busy={busy} onDecide={onDecide} />}
      {w?.type === 'reply' && <p className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">Waiting for {w.from} to reply on the phone.</p>}
      {w?.type === 'event' && <p className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">Waiting for the supplier to file GSTR-1A. Portal checks so far: {w.checks_done}.</p>}
      {d.status === 'needs_retry' && (
        <button type="button" disabled={busy} onClick={onRetry}
                className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"><RotateCw className="w-4 h-4" />Try again</button>
      )}

      {replies.length > 0 && (
        <div>
          <H>Replies</H>
          {replies.map((e, i) => (
            <p key={i} className="text-sm bg-gray-50 rounded-lg p-3 border mb-2">
              {d.voice_replies.includes(e.summary) && <Badge variant="info" size="xs" icon={Mic} className="mr-2">voice note</Badge>}
              {e.summary}
            </p>
          ))}
        </div>
      )}

      {d.workflow === 'W3' && d.snapshots.length > 0 && (
        <div>
          <H>Proof (SIMULATED portal)</H>
          <table className="w-full text-xs">
            <thead className="text-gray-400"><tr><th className="text-left">Invoice</th><th className="text-left">GSTR-2B</th><th className="text-left">Observed</th><th className="text-left">Snapshot</th></tr></thead>
            <tbody>
              {d.snapshots.map((s) => (
                <tr key={s.sha256} className="border-t border-gray-100">
                  <td className="py-1">{s.invoice_no}</td>
                  <td>{s.gstr2b_period.slice(0, 2)}-{s.gstr2b_period.slice(2)}: {s.in_gstr2b ? 'reported' : 'not reported'}</td>
                  <td>{s.taken_at.slice(0, 10).split('-').reverse().join('-')}</td>
                  <td className="font-mono">{s.sha256.slice(0, 12)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-gray-500 mt-1">Status on the purchase date: not available (no snapshot was taken then).</p>
          {w?.missing?.length > 0 && <p className="text-xs text-gray-600 mt-1"><FileCheck2 className="w-3.5 h-3.5 inline mr-1" />Missing: {w.missing.map((k) => DOCUMENT[k] ?? k).join(', ')}</p>}
        </div>
      )}

      <div>
        <H>Audit trail</H>
        <Timeline items={d.timeline} />
      </div>
    </div>
  );
}
