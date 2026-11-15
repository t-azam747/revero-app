import React, { useEffect, useState } from 'react';

export default function TrackButton({ jobId, index, existing }) {
  const [tracked, setTracked] = useState(existing || null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { if (existing) setTracked(existing); }, [existing]);
  async function track() {
    setBusy(true); setError('');
    try {
      const response = await fetch('/api/actions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: jobId, suggestion_index: index }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Couldn’t track this suggestion. Try again.');
      setTracked(data);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <span className="track-control"><button className="secondary" disabled={busy || !!tracked} onClick={track}>{tracked ? tracked.status === 'done' ? 'Done' : tracked.status === 'dismissed' ? 'Dismissed' : 'Tracked' : busy ? 'Tracking…' : 'Track this'}</button>{tracked?.status === 'open' && <small>Set an optional date in Actions.</small>}{error && <span role="alert" className="track-error">{error}</span>}</span>;
}
