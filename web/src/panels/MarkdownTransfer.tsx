/**
 * Markdown in and out, from the Contents tab (P2-13, P2-14, D15).
 *
 * ## Export is a link, not a fetch
 *
 * The two export routes are the one non-JSON corner of the API and they answer with a
 * `Content-Disposition: attachment` (phase-2 plan § 2, ruling 9). So the honest control for one
 * is an ordinary `<a href>`: the browser saves the file and names it from the header the server
 * already set, and the app neither holds the bytes in memory nor writes a second implementation
 * of the filename rules. It is also keyboard-reachable, right-clickable, and openable in a new
 * tab for free — a button wired to a blob URL is none of those and is more code.
 *
 * ## Import is a form, and it says what it lost
 *
 * A file dropped or picked, or Markdown pasted; one of the two modes; and — for `one-chapter` —
 * an optional name. The file is read in the browser and sent as text, because the route takes
 * JSON and a multipart upload would be a second request shape for one field.
 *
 * What matters most here is the **report**. An import can only append (ruling 5), so nothing it
 * does is destructive and none of this needs a confirmation; what it *can* do is quietly leave
 * something behind — a code fence, a link's target, a heading too deep for the schema. The
 * server names each one and where it was, and this panel shows the list until the writer
 * dismisses it. An import that silently edited somebody's file would be the friendly-sounding
 * version of data loss.
 */

import { useCallback, useId, useRef, useState } from 'react';
import type { ChangeEvent, DragEvent, FormEvent } from 'react';
import type { ImportMode, ImportNotice } from '../api';
import { IMPORT_MODES } from '../api';
import { plural } from '../format';
import { describeFailure, useProject } from '../state/ProjectContext';
import { useToasts } from '../state/ToastContext';

/** What a finished import left behind, held until the writer has read it. */
interface Report {
  chapters: string[];
  dropped: ImportNotice[];
}

interface MarkdownTransferProps {
  /** Opens a chapter once the import has created it. */
  onOpen: (documentId: string) => void;
}

export function MarkdownTransfer({ onOpen }: MarkdownTransferProps) {
  const { importMarkdown, manuscriptMarkdownUrl } = useProject();
  const { push } = useToasts();
  const [open, setOpen] = useState(false);
  const [markdown, setMarkdown] = useState('');
  const [source, setSource] = useState<string | null>(null);
  const [mode, setMode] = useState<ImportMode>(IMPORT_MODES.oneChapter);
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const [dropping, setDropping] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const ids = useId();

  const reset = useCallback(() => {
    setOpen(false);
    setMarkdown('');
    setSource(null);
    setTitle('');
    setMode(IMPORT_MODES.oneChapter);
  }, []);

  /** Read a dropped or chosen file into the box, so what is sent is what is on screen. */
  const take = useCallback(
    async (chosen: File) => {
      try {
        setMarkdown(await chosen.text());
        setSource(chosen.name);
        // A file named `chapter-seven.md` is almost certainly meant to be one chapter called
        // that. It is only a default — the field is right there, and it can be renamed after.
        setTitle((current) => current || chosen.name.replace(/\.(md|markdown|txt)$/i, ''));
      } catch (error: unknown) {
        push(`Could not read that file — ${describeFailure(error)}`, 'error');
      }
    },
    [push],
  );

  const onDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setDropping(false);
      const dropped = event.dataTransfer?.files?.[0];
      if (dropped) {
        void take(dropped);
      }
    },
    [take],
  );

  const onPick = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const chosen = event.target.files?.[0];
      if (chosen) {
        void take(chosen);
      }
    },
    [take],
  );

  const submit = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      if (busy) {
        return;
      }
      setBusy(true);
      try {
        const named = mode === IMPORT_MODES.oneChapter ? title.trim() : '';
        const result = await importMarkdown(markdown, mode, named || undefined);
        const created = result.documents;
        setReport({ chapters: created.map((meta) => meta.title), dropped: result.dropped });
        reset();
        push(`Imported ${plural(created.length, 'chapter')}.`);
        const first = created[0];
        if (first) {
          onOpen(first.id);
        }
      } catch (error: unknown) {
        push(`Could not import that file — ${describeFailure(error)}`, 'error');
      } finally {
        setBusy(false);
      }
    },
    [busy, importMarkdown, markdown, mode, onOpen, push, reset, title],
  );

  return (
    <div className="md-transfer">
      <div className="md-transfer-actions">
        <a className="md-export" href={manuscriptMarkdownUrl()} download>
          Export manuscript
        </a>
        <button type="button" aria-expanded={open} onClick={() => setOpen((was) => !was)}>
          {open ? 'Cancel import' : 'Import Markdown…'}
        </button>
      </div>

      {open && (
        <form className="md-import" onSubmit={(event) => void submit(event)}>
          <fieldset>
            <legend>How should the file be read?</legend>
            <label htmlFor={`${ids}-one`}>
              <input
                id={`${ids}-one`}
                type="radio"
                name={`${ids}-mode`}
                value={IMPORT_MODES.oneChapter}
                checked={mode === IMPORT_MODES.oneChapter}
                onChange={() => setMode(IMPORT_MODES.oneChapter)}
              />
              As one chapter
            </label>
            <label htmlFor={`${ids}-split`}>
              <input
                id={`${ids}-split`}
                type="radio"
                name={`${ids}-mode`}
                value={IMPORT_MODES.splitOnH1}
                checked={mode === IMPORT_MODES.splitOnH1}
                onChange={() => setMode(IMPORT_MODES.splitOnH1)}
              />
              A chapter per top-level heading
            </label>
          </fieldset>

          {mode === IMPORT_MODES.oneChapter && (
            <label className="md-import-title" htmlFor={`${ids}-title`}>
              Chapter name
              <input
                id={`${ids}-title`}
                value={title}
                placeholder="Left blank, it is named like any new chapter"
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>
          )}

          <div
            className={dropping ? 'md-drop is-over' : 'md-drop'}
            onDragOver={(event) => {
              event.preventDefault();
              setDropping(true);
            }}
            onDragLeave={() => setDropping(false)}
            onDrop={onDrop}
          >
            <label htmlFor={`${ids}-markdown`}>Markdown</label>
            <textarea
              id={`${ids}-markdown`}
              rows={6}
              value={markdown}
              placeholder="Paste Markdown here, or drop a file onto this box."
              onChange={(event) => {
                setMarkdown(event.target.value);
                setSource(null);
              }}
            />
            <div className="md-drop-file">
              <input
                ref={file}
                id={`${ids}-file`}
                type="file"
                accept=".md,.markdown,.txt,text/markdown,text/plain"
                onChange={onPick}
              />
              {source !== null && <span className="md-drop-name">Read from {source}</span>}
            </div>
          </div>

          <div className="md-import-actions">
            <button type="submit" disabled={busy || markdown.trim().length === 0}>
              {busy ? 'Importing…' : 'Import'}
            </button>
            <button type="button" onClick={reset}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {report !== null && (
        <div className="md-report" role="status" aria-label="What the import did">
          <p>
            Added {plural(report.chapters.length, 'chapter')}: {report.chapters.join(', ')}.
          </p>
          {report.dropped.length === 0 ? (
            <p>Nothing was left behind.</p>
          ) : (
            <>
              <p>
                {plural(report.dropped.length, 'thing')} the manuscript cannot hold
                {report.dropped.length === 1 ? ' was' : ' were'} changed:
              </p>
              <ul className="md-dropped">
                {report.dropped.map((notice, index) => (
                  <li key={`${notice.element}-${notice.line}-${index}`}>
                    <strong>{notice.element}</strong> on line {notice.line} — {notice.detail}
                  </li>
                ))}
              </ul>
            </>
          )}
          <button type="button" onClick={() => setReport(null)}>
            Dismiss report
          </button>
        </div>
      )}
    </div>
  );
}
