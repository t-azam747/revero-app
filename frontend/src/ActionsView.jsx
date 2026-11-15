import React, { useEffect, useState } from 'react';

export default function ActionsView() {
  const [actions, setActions] = useState([]);
  const [filter, setFilter] = useState('open');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    fetch(`/api/actions?status=${filter}`).then(async response => {
      if (!response.ok) throw new Error('Couldn’t load actions. Please retry.');
      const data = await response.json();
      if (active) setActions(data);
    }).catch(err => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [filter, version]);
  function updated(action) { setActions(current => current.map(item => item.id === action.id ? action : item).filter(item => item.status === filter)); }
  return <section className="actions-view" aria-label="Tracked actions">
    <h1>Make it happen.</h1><p className="aside-note">Ideas you’ve chosen to act on. Dates are always yours to confirm.</p>
    <div className="action-filters" aria-label="Filter actions">{['open', 'done', 'dismissed'].map(status => <button key={status} aria-pressed={filter === status} onClick={() => setFilter(status)}>{status === 'open' ? 'Open' : status === 'done' ? 'Done' : 'Dismissed'}</button>)}</div>
    {loading ? <p role="status">Loading actions…</p> : error ? <div role="alert"><p>{error}</p><button className="secondary" onClick={() => setVersion(version + 1)}>Retry loading actions</button></div> : !actions.length ? <p className="actions-empty">{filter === 'open' ? 'No open actions. Choose “Track this” beside a Reel’s suggestion to start.' : `No ${filter} actions.`}</p> : <div className="action-list">{actions.map(action => <ActionCard key={action.id} action={action} onUpdated={updated}/>)}</div>}
  </section>;
}

function ActionCard({ action, onUpdated }) {
  const [date, setDate] = useState(action.due_date || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function update(fields) {
    setBusy(true); setError(''); setNotice('');
    try {
      const response = await fetch(`/api/actions/${action.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fields) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Couldn’t save the action. Check the date and try again.');
      onUpdated(data); setDate(data.due_date || ''); setNotice(data.due_date ? 'Confirmed date saved.' : 'Saved without a due date.');
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <article className="action-card" aria-label={action.text}>
    <h2>{action.text}</h2><a className="action-reel" href={action.url} target="_blank" rel="noreferrer">Reel / {action.shortcode} ↗</a>
    <blockquote><p>{action.source_excerpt}</p><cite>{action.source_origin}{action.timestamp_seconds != null ? ` at ${action.timestamp_seconds}s` : ''}</cite></blockquote>
    {!!action.date_mentions.length && <p className="date-wording">Dates in this source: {action.date_mentions.map(text => `“${text}”`).join(', ')}. Choose a date only if it applies to this action.</p>}
    <p className="due-date">{action.due_date ? `Confirmed due date: ${action.due_date}` : 'No confirmed due date'}</p>
    {action.status === 'open' && <><form className="date-form" onSubmit={event => { event.preventDefault(); update({ due_date: date || null }); }}><label htmlFor={`due-${action.id}`}>Due date (optional)</label><div><input id={`due-${action.id}`} type="date" value={date} disabled={busy} onChange={event => setDate(event.target.value)}/><button className="secondary" disabled={busy} type="submit">{date ? 'Confirm date' : 'Save without date'}</button>{action.due_date && <button className="text-button" type="button" disabled={busy} onClick={() => update({ due_date: null })}>Remove date</button>}</div></form>
      <div className="action-controls"><button className="primary" disabled={busy} onClick={() => update({ status: 'done' })}>Done</button><button className="secondary" disabled={busy} onClick={() => update({ status: 'dismissed' })}>Dismiss</button></div></>}
    {notice && <p role="status" className="action-notice">{notice}</p>}{error && <p role="alert" className="job-error">{error}</p>}
  </article>;
}
