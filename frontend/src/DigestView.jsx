import React, { useEffect, useRef, useState } from 'react';

export default function DigestView() {
  const [data, setData] = useState(null);
  const [interests, setInterests] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [deliveryTime, setDeliveryTime] = useState('23:00');
  const manualKey = useRef(sessionStorage.getItem('revero-digest-request'));
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function refresh(reset = false) {
    const response = await fetch('/api/digest');
    if (!response.ok) throw new Error('Couldn’t load the digest. Check the backend and retry.');
    const value = await response.json(); setData(value);
    if (reset) { setInterests(value.preferences.interests.join(', ')); setEnabled(value.preferences.enabled); setDeliveryTime(value.preferences.delivery_time || '23:00'); }
  }
  useEffect(() => { refresh(true).catch(err => setError(err.message)); const timer = setInterval(() => { if (!inFlight.current) refresh().catch(() => {}); }, 3000); return () => clearInterval(timer); }, []);
  async function perform(url, method, body, message) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true); setError(''); setNotice('');
    try {
      const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Couldn’t save this change. Check the interests and try again.');
      if (url === '/api/digest/send' && result.state === 'sent') { manualKey.current = null; sessionStorage.removeItem('revero-digest-request'); }
      await refresh(); setNotice(result.state ? `Delivery status: ${result.state}.` : message);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); inFlight.current = false; }
  }
  async function sendNow() {
    if (!manualKey.current) { manualKey.current = crypto.randomUUID(); sessionStorage.setItem('revero-digest-request', manualKey.current); }
    await perform('/api/digest/send', 'POST', { request_id: manualKey.current });
  }
  if (!data) return <section className="digest-view"><h1>Your evening rewind.</h1>{error ? <div role="alert"><p>{error}</p><button className="secondary" onClick={() => { setError(''); refresh(true).catch(err => setError(err.message)); }}>Retry loading digest</button></div> : <p role="status">Loading digest…</p>}</section>;
  const { preview, preferences, runs } = data;
  const today = runs.find(run => run.local_date === preview.local_date);
  return <section className="digest-view" aria-label="Daily digest"><h1>Your evening rewind.</h1><p className="view-intro">Today’s readable Reels, with the three most useful takeaways highlighted, plus your confirmed deadlines. Scheduled for {preferences.delivery_time || '23:00'} Asia/Kolkata when this computer and worker are running.</p>
    <form className="digest-settings" onSubmit={event => { event.preventDefault(); perform('/api/digest/preferences', 'PUT', { interests: interests.split(',').map(value => value.trim()).filter(Boolean), enabled, delivery_time: deliveryTime }, 'Digest preferences saved.'); }}><label htmlFor="interests">Your interests (separate with commas)</label><input id="interests" value={interests} onChange={event => setInterests(event.target.value)} placeholder="backend interviews, cooking, fitness" disabled={busy}/><label className="schedule-toggle"><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} disabled={busy || (!preferences.telegram_configured && !enabled)}/>Send daily on Telegram</label><label htmlFor="digest-time">Daily delivery time (Asia/Kolkata)</label><input id="digest-time" type="time" required value={deliveryTime} onChange={event => setDeliveryTime(event.target.value)} disabled={busy}/><button className="secondary" disabled={busy}>Save preferences</button></form>
    {!preferences.telegram_configured && <p className="setup-note">Telegram isn’t configured. Add your bot token and private chat ID to the backend .env. You can still preview and rank your digest here.</p>}
    <section className="digest-preview" aria-label="Digest preview"><div className="content-heading"><h2>Preview for {preview.local_date}</h2><button aria-label="Refresh digest preview" disabled={busy} onClick={() => refresh().catch(err => setError(err.message))}>↻</button></div>
      {today && <p className="content-status">Today’s delivery: {today.state}</p>}
      {today && <p className="privacy-note">A delivery already started today. Retries reuse its saved snapshot; this preview shows your current saves.</p>}
      {!preview.picks.length && <p>No ready Reels yet. Add a caption or clip to a saved Reel first.</p>}
      <ol className="digest-picks">{preview.picks.map(reel => <li key={reel.id}><h3>{reel.summary}</h3><a href={reel.url} target="_blank" rel="noreferrer">Reel / {reel.shortcode} ↗</a><details><summary>Why this pick?</summary><p>Score: {reel.score}. Interest matches: {reel.reasons.interest_matches.join(', ') || 'none'}. Actionable suggestions: {reel.reasons.actionable_suggestions}. Source excerpts: {reel.reasons.source_count}. Recency breaks ties.</p></details></li>)}</ol>
      {(preview.readable_reels || []).length > preview.picks.length && <details><summary>More readable Reels from today</summary><ul>{preview.readable_reels.filter(reel => !preview.picks.some(pick => pick.id === reel.id)).map(reel => <li key={reel.id}>{reel.summary}</li>)}</ul></details>}
      <h3>Upcoming and overdue actions</h3><p className="privacy-note">Confirmed dates through the next seven days, including actions from Reels outside the top three.</p>
      {!preview.deadlines.length ? <p>No confirmed deadlines.</p> : <ul className="digest-deadlines">{preview.deadlines.map(action => <li key={action.id}><strong>{action.due_date}</strong> {action.text} <a href={action.url} target="_blank" rel="noreferrer">Source Reel ↗</a></li>)}</ul>}
      <p className="pending-count">{preview.pending_count} saved link(s) still need content or processing.</p>
      {preview.unreadable_count !== undefined && <p>{preview.unreadable_count} need readable content or have failed processing; {preview.processing_count} queued or processing.</p>}
      <button className="primary" disabled={busy || !preferences.telegram_configured || (data.manual_runs || []).some(run => ['sending', 'uncertain'].includes(run.state))} onClick={sendNow}>Send digest now</button><p className="privacy-note">Sends to the configured private chat. Manual sends have separate records and do not consume the scheduled digest. Previewing sends nothing.</p>
    </section>
    {!!data.manual_runs?.length && <section className="digest-history"><h2>Manual delivery history</h2>{data.manual_runs.map(run => <article key={run.run_id}><h3>{run.local_date}: {run.state}</h3>{run.error && <p>{run.error}</p>}{run.state === 'failed' && <button disabled={busy} onClick={() => { manualKey.current = run.run_id; sessionStorage.setItem('revero-digest-request', run.run_id); sendNow(); }}>Retry manual delivery</button>}{run.state === 'uncertain' && <><p>Check the last attempted message in Telegram before retrying.</p>{['delivered', 'not_delivered'].map(decision => <button key={decision} disabled={busy} onClick={() => perform(`/api/digest/manual/${run.run_id}/resolve`, 'POST', {decision})}>Confirm manual part {decision.replace('_', ' ')}</button>)}</>}</article>)}</section>}
    {!!runs.length && <section className="digest-history"><h2>Delivery history</h2>{runs.map(run => <article key={run.local_date}><h3>{run.local_date}: {run.state}</h3>{run.error && <p>{run.error}</p>}{run.state === 'failed' && run.next_attempt_at > Date.now()/1000 && <p>Next retry after {new Date(run.next_attempt_at*1000).toLocaleString()}.</p>}{run.state === 'uncertain' && <><p>Check the message in Telegram before resolving this run. Automatic delivery is paused for this date.</p><p className="privacy-note">If the digest has several messages, check the last attempted part. Confirm only that part; delivered parts will not be resent.</p><button className="secondary" disabled={busy} onClick={() => perform(`/api/digest/${run.local_date}/resolve`, 'POST', { decision: 'delivered' })}>Confirm last part was delivered</button>{run.local_date === preview.local_date && <button className="secondary" disabled={busy} onClick={() => perform(`/api/digest/${run.local_date}/resolve`, 'POST', { decision: 'not_delivered' })}>Confirm last part was not delivered</button>}</>}</article>)}</section>}
    {notice && <p role="status" className="action-notice">{notice}</p>}{error && <p role="alert" className="job-error">{error}</p>}
  </section>;
}
