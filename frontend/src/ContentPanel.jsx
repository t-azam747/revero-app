import React, { useEffect, useState } from 'react';
import TrackButton from './TrackButton';

const labels = { needs_content: 'Needs content', queued: 'Queued', processing: 'Processing', ready: 'Ready', failed: 'Failed' };
export { labels };

export default function ContentPanel({ reel, onStatus, onClose }) {
  const [trackedActions, setTrackedActions] = useState([]);
  const [job, setJob] = useState(null);
  const [caption, setCaption] = useState('');
  const [video, setVideo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState('');
  const [config, setConfig] = useState(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const [contentResponse, configResponse, actionsResponse] = await Promise.all([fetch(`/api/reels/${reel.id}/content`), fetch('/api/processing'), fetch(`/api/actions?status=all&reel_id=${reel.id}`)]);
        if (!contentResponse.ok || !configResponse.ok || !actionsResponse.ok) throw new Error('Couldn’t load content. Check the backend connection.');
        const content = await contentResponse.json();
        const processing = await configResponse.json();
        const actions = await actionsResponse.json();
        if (active) { setJob(content.job); setTrackedActions(actions); setConfig(processing); setLoaded(true); setPollError(''); onStatus(reel.id, content.reel.status); }
      } catch (err) { if (active) setPollError(err.message); }
    }
    refresh();
    const timer = setInterval(refresh, 2500);
    return () => { active = false; clearInterval(timer); };
  }, [reel.id]);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const body = new FormData(); body.append('caption', caption);
      if (video) body.append('video', video);
      const response = await fetch(`/api/reels/${reel.id}/content`, { method: 'POST', body });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Couldn’t attach this content.');
      setJob(data); onStatus(reel.id, data.state);
      setCaption(''); setVideo(null); event.target.reset();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function retry() {
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/reels/${reel.id}/retry`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Couldn’t retry.');
      setJob(data); onStatus(reel.id, data.state);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <section className="content-panel" aria-label={`Content for ${reel.url ? reel.shortcode : `Instagram DM save ${reel.id}`}`}>
    <div className="content-heading"><h2>{reel.url ? `Reel / ${reel.shortcode}` : `Instagram DM save #${reel.id}`}</h2><button onClick={onClose} aria-label="Close content">×</button></div>
    <p className="content-status" role="status">{labels[job?.state || reel.status]}</p>
    {!loaded && !pollError && <p>Loading content…</p>}
    {config && !config.configured && <p className="setup-note">Gemini isn’t configured yet. You can attach content now; it will stay queued until the backend is configured and the worker is running.</p>}
    {job?.error && <p className="job-error">{job.error}{job.state === 'queued' && job.available_at > 0 ? ` Next attempt: ${new Date(job.available_at * 1000).toLocaleString()}.` : ''}</p>}
    {job?.state === 'failed' && <button className="secondary" disabled={busy} onClick={retry}>Retry extraction</button>}
    {job?.takeaway && <article className="takeaway"><span className="result-label">{job.caption_only ? 'Caption-only takeaway' : 'Video takeaway'}</span><h3>{job.takeaway.summary}</h3>
      <div className="topics">{job.takeaway.topics.map((topic, i) => <span key={i}>{topic}</span>)}</div>
      {!!job.takeaway.suggestions.length && <><h4>Ideas to try</h4><ul>{job.takeaway.suggestions.map((item, i) => <li key={i}>{item.text} <a href={`#source-${job.id}-${item.source_index}`}>[Source {item.source_index + 1}]</a><TrackButton key={`${job.id}-${i}`} jobId={job.id} index={i} existing={trackedActions.find(action => action.job_id === job.id && action.suggestion_index === i)}/></li>)}</ul></>}
      {!!job.takeaway.walkthrough?.length && <><h4>Tutorial Walkthrough</h4><ol className="walkthrough-steps">{job.takeaway.walkthrough.map((step, i) => <li key={i}><strong>Step {step.step_number}:</strong> {step.instruction} {step.spoken_text && <small className="walkthrough-spoken">🗣️ “{step.spoken_text}”</small>} {step.on_screen_text && <small className="walkthrough-screen">🖥️ [{step.on_screen_text}]</small>} {(step.timestamp_start != null || step.timestamp_end != null) && <span className="walkthrough-time">⏱️ {step.timestamp_start != null ? `${step.timestamp_start}s` : ''}{step.timestamp_end != null ? ` - ${step.timestamp_end}s` : ''}</span>} {step.source_index != null && <a href={`#source-${job.id}-${step.source_index}`}>[Source {step.source_index + 1}]</a>}</li>)}</ol></>}
      {!!job.takeaway.uncertainties?.length && <><h4>Uncertainties / Unclear Details</h4><ul className="uncertainties-list">{job.takeaway.uncertainties.map((u, i) => <li key={i}>⚠️ {u}</li>)}</ul></>}
      {!!job.takeaway.date_candidates.length && <><h4>Dates mentioned</h4><ul>{job.takeaway.date_candidates.map((date, i) => <li key={i}>“{date.original_text}” <a href={`#source-${job.id}-${date.source_index}`}>[Source {date.source_index + 1}]</a> <small>Not a confirmed deadline</small></li>)}</ul></>}
      <h4>Source excerpts</h4>{job.takeaway.sources.map((source, i) => <blockquote key={i} id={`source-${job.id}-${i}`}><p>{source.excerpt}</p><cite>Source {i + 1}: {source.origin}{source.timestamp_seconds != null ? ` at ${Math.floor(source.timestamp_seconds / 60)}:${String(Math.floor(source.timestamp_seconds % 60)).padStart(2, '0')}` : ''}</cite></blockquote>)}
    </article>}
    <form onSubmit={submit} className="content-form"><label htmlFor="caption">Add or replace content</label><textarea id="caption" maxLength={20000} rows={4} value={caption} onChange={event => setCaption(event.target.value)} placeholder="Paste the Reel’s caption or relevant text…" disabled={busy}/>
      <label htmlFor="video">Or attach a clip (MP4, MOV, WebM; up to 10 MiB)</label><input id="video" type="file" accept="video/mp4,video/quicktime,video/webm" disabled={busy} onChange={event => { const file = event.target.files[0]; if (file && file.size > 10 * 1024 * 1024) { setError('Choose a clip smaller than 10 MiB.'); event.target.value = ''; setVideo(null); } else { setVideo(file || null); setError(''); } }}/>
      <p className="privacy-note">Processing sends this caption or clip to Google Gemini. Google may use free-tier inputs to improve its products. Only attach content you want to send.</p>
      <button className="primary" disabled={!loaded || busy || (!caption.trim() && !video)}>{busy ? 'Attaching…' : 'Attach & queue'}</button>
    </form>{pollError && <p role="alert" className="job-error">{pollError} Retrying automatically.</p>}{error && <p role="alert" className="job-error">{error}</p>}
  </section>;
}
