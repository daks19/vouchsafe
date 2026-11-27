import React, { useState } from 'react';
import { CalendarClock, RotateCcw, MessageSquare } from 'lucide-react';

// Rehearsal helpers, clearly marked. On stage the reply comes from the phone instead.
export default function DemoControls({ detail, busy, onDay, onReply, onReset }) {
  const [text, setText] = useState('');
  const type = detail?.waiting?.type;
  const btn = 'inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50';
  return (
    <div className="rounded-xl border border-dashed border-gray-300 p-3 space-y-2">
      <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-400">Demo</p>
      <div className="flex flex-wrap gap-2 items-center">
        {type === 'event' && <button type="button" className={btn} disabled={busy} onClick={onDay}><CalendarClock className="w-3.5 h-3.5" />A day passes</button>}
        {type === 'reply' && (
          <form className="flex gap-2 flex-1" onSubmit={(e) => { e.preventDefault(); onReply(text); setText(''); }}>
            <input className="form-input-base flex-1" placeholder="Type a reply as the shop" value={text} onChange={(e) => setText(e.target.value)} aria-label="Type a reply as the shop" />
            <button type="submit" className={btn} disabled={busy || !text.trim()}><MessageSquare className="w-3.5 h-3.5" />Send reply</button>
          </form>
        )}
        <button type="button" className={btn} disabled={busy} onClick={onReset}><RotateCcw className="w-3.5 h-3.5" />Reset scenario</button>
      </div>
    </div>
  );
}
