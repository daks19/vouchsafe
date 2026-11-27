import React, { useCallback, useEffect, useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import { caseAction, getCase, getCases, getClients, post } from './api';
import ClientList from './components/ClientList';
import Readiness from './components/Readiness';
import CaseQueue from './components/CaseQueue';
import StatTile from './components/ui/StatTile';
import CaseDetail from './components/CaseDetail';
import DemoControls from './components/DemoControls';

const POLL_MS = 2000;

export default function App() {
  const [data, setData] = useState(null);
  const [clients, setClients] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const d = await getCases();
      setData(d);
      if (selectedId) setDetail(await getCase(selectedId));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, [selectedId]);

  useEffect(() => { getClients().then(setClients).catch((e) => setError(e.message)); }, []);
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  // One request at a time; buttons stay disabled while it runs (sending a voice note takes a few seconds).
  const act = async (fn) => {
    setBusy(true);
    setToast(null);
    try {
      await fn();
    } catch (e) {
      setToast(e.message);
    } finally {
      setBusy(false);
      refresh();
    }
  };
  const on = (action) => (body) => act(() => caseAction(selectedId, action, body));

  const cases = data?.cases ?? [];
  const count = (...s) => cases.filter((c) => s.includes(c.status)).length;

  return (
    <div className="min-h-screen">
      <div role="status" className="bg-amber-100 border-b border-amber-300 text-amber-900 text-sm px-6 py-2 flex items-center gap-2">
        <ShieldAlert className="w-4 h-4 shrink-0" />
        <span><b>SIMULATED:</b> mock GST portal and fictional data.{' '}
          {data?.channel === 'telegram'
            ? 'Telegram messages are real and go only to the demo chat.'
            : 'Messages are simulated.'}
        </span>
      </div>
      {error && <div role="alert" className="bg-red-50 text-red-700 text-sm px-6 py-2">{error}</div>}
      {(toast || data?.last_error) && (
        <div role="alert" className="fixed bottom-6 right-6 z-10 max-w-md rounded-xl bg-red-600 text-white text-sm px-4 py-3 shadow-lg">
          {toast || data.last_error}
          {toast && <button type="button" className="ml-3 underline" onClick={() => setToast(null)}>Dismiss</button>}
        </div>
      )}
      <header className="px-6 pt-5">
        <h1 className="text-2xl font-display font-bold text-gray-900">Vouchsafe <span className="text-gray-400 font-medium">CA workspace</span></h1>
      </header>
      <main className="p-6 grid gap-6 grid-cols-[250px_minmax(0,1.2fr)_minmax(0,1fr)]">
        <ClientList clients={clients} />
        <section className="space-y-4" aria-label="Cases">
          <Readiness resolved={data?.readiness.resolved ?? 0} total={data?.readiness.total ?? 0} />
          <div className="grid grid-cols-4 gap-3">
            <StatTile value={cases.length - count('resolved')} label="Open" tone="neutral" />
            <StatTile value={count('waiting_approval', 'waiting_ca', 'needs_retry')} label="Waiting on you" tone="warning" />
            <StatTile value={count('waiting_reply', 'waiting_supplier')} label="Waiting on others" tone="accent" />
            <StatTile value={count('resolved')} label="Resolved" tone="success" />
          </div>
          <CaseQueue cases={cases} selectedId={selectedId} onSelect={setSelectedId} />
        </section>
        <section className="card p-6 space-y-5 self-start" aria-label="Case detail">
          {detail
            ? <CaseDetail detail={detail} busy={busy}
                          onApprove={(approve, sha256) => on('approve')({ approve, sha256 })}
                          onDecide={on('decide')} onRetry={() => on('retry')()} />
            : <p className="text-gray-400">Select a case to see what it is waiting for.</p>}
          <DemoControls detail={detail} busy={busy}
                        onDay={() => on('day')()} onReply={(text) => on('reply')({ text })}
                        onReset={() => act(async () => { await post('/api/reset'); setDetail(null); setSelectedId(null); })} />
        </section>
      </main>
    </div>
  );
}
