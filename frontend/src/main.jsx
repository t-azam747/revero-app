import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import ContentPanel, { labels } from './ContentPanel';
import ActionsView from './ActionsView';
import AskView from './AskView';
import DigestView from './DigestView';

function App() {
  const [view, setView] = useState('inbox');
  const [selected, setSelected] = useState(null);
  function updateStatus(id, status) { setReels(current => current.map(reel => reel.id === id ? { ...reel, status } : reel)); }
  const [reels, setReels] = useState([]);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const end = useRef(null);
  async function load() {
    setLoading(true); setLoadError('');
    try {
      const response = await fetch('/api/reels');
      if (!response.ok) throw new Error();
      setReels(await response.json());
    } catch { setLoadError('Couldn’t load your Reels. Check that the backend is running, then retry.'); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [messages]);
  async function send(event) {
    event.preventDefault();
    if (sending || !input.trim()) return;
    const url = input.trim();
    setSending(true);
    setMessages(current => [...current, { role: 'user', text: url }]);
    try {
      const response = await fetch('/api/reels', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Please enter a valid Instagram Reel link.');
      setReels(current => current.some(reel => reel.id === data.id) ? current : [...current, data].sort((a,b) => a.id-b.id));
      setMessages(current => [...current, { role: 'assistant', text: data.created ? 'Saved to your inbox.' : 'Already saved. This Reel is in your inbox.', reel: data }]);
      setInput('');
    } catch (error) {
      setMessages(current => [...current, { role: 'error', text: error instanceof TypeError ? 'Couldn’t reach Revero. Check that the backend is running and try again.' : error.message }]);
    } finally { setSending(false); }
  }
  return <div className="workspace">
    <aside><a className="brand" href="/" aria-label="Revero home"><span className="logo">r</span>revero</a>
      <nav className="workspace-nav" aria-label="Workspace"><button aria-pressed={view === 'inbox'} onClick={() => setView('inbox')}>Inbox</button><button aria-pressed={view === 'actions'} onClick={() => setView('actions')}>Actions</button><button aria-pressed={view === 'ask'} onClick={() => setView('ask')}>Ask</button><button aria-pressed={view === 'digest'} onClick={() => setView('digest')}>Digest</button></nav><div className="inbox-title"><h2>Your inbox</h2><span>{reels.length}</span></div>
      <p className="aside-note">A place for the things you want to come back to.</p>
      {loading ? <p role="status">Loading your Reels…</p> : loadError ? <div role="alert"><p>{loadError}</p><button onClick={load}>Retry</button></div> : reels.length === 0 ? <div className="empty-inbox"><span>▤</span><p>Your first save goes here.</p></div> : <ol className="saved-list">{reels.map(reel => <li key={reel.id}><>{reel.url ? <a href={reel.url} target="_blank" rel="noreferrer">Reel / {reel.shortcode}<span>Open on Instagram ↗</span></a> : <p>Instagram DM save #{reel.id}<span>Reference only · add a caption or clip</span></p>}</><small>{labels[reel.status] || reel.status}</small><button className="content-link" onClick={() => { setView('inbox'); setSelected(reel); }}>View / add content</button></li>)}</ol>}
      <footer>Saved on this computer<span>No account needed</span></footer>
    </aside>
    <main><header><span>{{inbox: 'Reel inbox', actions: 'Actions', ask: 'Ask your saves', digest: 'Daily digest'}[view]}</span><span className="local"><i/> Local workspace</span></header>
      <div className="conversation">{view === 'ask' ? <AskView/> : view === 'digest' ? <DigestView/> : view === 'actions' ? <ActionsView/> : <>{selected ? <ContentPanel key={selected.id} reel={selected} onStatus={updateStatus} onClose={() => setSelected(null)}/> : <section className="welcome"><div className="bookmark" aria-hidden="true">▱</div><h1>Good ideas deserve<br/>a second look.</h1><p>Drop an Instagram Reel here.<br/>Keep it somewhere you’ll find it again.</p></section>}
      <div className="messages" role="log" aria-label="Chat messages" aria-live="polite">{messages.map((message, index) => <div key={index} className={`message ${message.role}`}><span className="speaker">{message.role === 'user' ? 'You' : 'Revero'}</span><p>{message.text}</p>{message.reel && <a href={message.reel.url} target="_blank" rel="noreferrer">Reel / {message.reel.shortcode} ↗</a>}</div>)}<div ref={end}/></div></>}</div>
      {view === 'inbox' && <div className="composer-area"><form onSubmit={send}><label htmlFor="reel-url" className="sr-only">Instagram Reel link</label><input id="reel-url" value={input} onChange={event => setInput(event.target.value)} placeholder="Paste an Instagram Reel link…" autoComplete="off" disabled={sending}/><button type="submit" disabled={sending || !input.trim()}>{sending ? 'Saving…' : 'Send'}</button></form><p>Save a link, then choose View / add content to extract a takeaway.</p></div>}
    </main>
  </div>;
}
createRoot(document.getElementById('root')).render(<App/>);
