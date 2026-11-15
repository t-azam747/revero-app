import React, { useRef, useState, useEffect } from 'react';

export default function AskView() {
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const end = useRef(null);
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }, [messages]);
  async function ask(event) {
    event.preventDefault();
    if (busy || !question.trim()) return;
    const text = question.trim(); setBusy(true);
    try {
      const response = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: text }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Couldn’t answer this question. Try again.');
      setMessages(current => [...current, { question: text, ...data }]);
      if (['answered', 'no_match'].includes(data.status)) setQuestion('');
    } catch (err) { setMessages(current => [...current, { question: text, status: 'error', answer: err.message, claims: [], sources: [] }]); }
    finally { setBusy(false); }
  }
  return <section className="ask-view" aria-label="Ask your saved Reels"><h1>Find the idea again.</h1><p className="view-intro">Ask about your saved captions and takeaways. Answers point back to the excerpts that support them.</p>
    <div role="log" aria-live="polite" aria-label="Question answers" className="answer-log">{messages.map((message, index) => <article key={index} className="answer-card"><h2>{message.question}</h2>
      {message.claims.length ? message.claims.map((claim, ci) => <p key={ci}>{claim.text} {claim.source_ids.map(id => <a key={id} href={`#answer-${index}-${message.sources.findIndex(source => source.id === id)}`}>[Source {message.sources.findIndex(source => source.id === id) + 1}]</a>)}</p>) : <p role={message.status === 'error' ? 'alert' : undefined}>{message.answer}</p>}
      {!!message.sources.length && <div className="answer-sources"><h3>{message.status === 'answered' ? 'Supporting excerpts' : 'Related excerpts'}</h3>{message.sources.map((source, si) => <blockquote key={source.id} id={`answer-${index}-${si}`}><p>{source.excerpt}</p><cite>Source {si+1}: {source.origin}{source.timestamp_seconds != null ? ` at ${source.timestamp_seconds}s` : ''}</cite><a href={source.url} target="_blank" rel="noreferrer">Reel / {source.shortcode} ↗</a></blockquote>)}</div>}
    </article>)}<div ref={end}/></div>
    <form className="ask-form" onSubmit={ask}><label htmlFor="question">Question about your saves</label><textarea id="question" rows={3} maxLength={1000} value={question} onChange={event => setQuestion(event.target.value)} placeholder="What did I save about backend interviews?" disabled={busy}/><button className="primary" disabled={busy || !question.trim()}>{busy ? 'Looking through your saves…' : 'Ask Revero'}</button></form><p className="privacy-note">Related excerpts are sent to Gemini to answer. If no relevant evidence is found, no model call is made.</p>
  </section>;
}
