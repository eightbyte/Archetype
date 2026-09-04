/**
 * One entry's relationships (P3-14, ruling 7, ruling 9).
 *
 * Both directions in one list, each labelled the way **this** entry's end reads it: "is a member
 * of" from one side and "has as a member" from the other. A symmetric relation is one row and
 * appears once from each side, never twice from either.
 *
 * ## An illegal link cannot be built
 *
 * That is the point of the add form's shape. The writer chooses the *other entry* first, and the
 * relation picker is then built from the vocabulary for those two kinds — so a `place` that
 * `knows` an `item` is never on offer, rather than being offered and refused. The server refuses
 * it anyway, because that is where the rule lives; a form that offers a choice and then rejects
 * it has taught the writer something untrue about their own bible.
 *
 * The relation list comes from `relationOptions`, which reads the served definition. Nothing here
 * knows what the twelve relations are.
 *
 * ## Bounds are stored, displayed, and never interpreted
 *
 * `since` and `until` are free text (D9). Nothing sorts by them, here or in Phase 8; the relation
 * that carries ordering power is `precedes`, and it does so through the ordering module, which
 * reads edges. A bound is genuinely nullable, so clearing one sends `null`.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { BibleSchema, Entry, LinkView } from '../api/types';
import { LINK_ENDS } from '../api/types';
import { kindLabel, relationOptions } from '../bibleSchema';
import type { RelationOption } from '../bibleSchema';
import { useBible } from '../state/BibleContext';
import { describeFailure } from '../state/ProjectContext';
import { useToasts } from '../state/ToastContext';

export interface EntryLinksPanelProps {
  entry: Entry;
  schema: BibleSchema;
  links: LinkView[];
  /** Something changed — the detail view re-reads the links and the entry's link count. */
  onChanged: () => void;
  /** Open another entry, from a link on this one. */
  onOpen: (entryId: string) => void;
}

export function EntryLinksPanel({
  entry,
  schema,
  links,
  onChanged,
  onOpen,
}: EntryLinksPanelProps) {
  const { listCandidates, createLink, deleteLink, patchLink } = useBible();
  const { push } = useToasts();
  const [candidates, setCandidates] = useState<Entry[]>([]);
  const [targetId, setTargetId] = useState('');
  const [choice, setChoice] = useState('');
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const found = await listCandidates();
        if (live) {
          setCandidates(found.filter((other) => other.id !== entry.id));
        }
      } catch {
        // A picker that could not be filled is an add form that cannot be used; the list of
        // existing links above it is unaffected, and that is the part worth keeping on screen.
        if (live) {
          setCandidates([]);
        }
      }
    })();
    return () => {
      live = false;
    };
  }, [entry.id, listCandidates]);

  const target = candidates.find((other) => other.id === targetId) ?? null;

  const options = useMemo(
    () => (target === null ? [] : relationOptions(schema, entry.kind, target.kind)),
    [entry.kind, schema, target],
  );

  const chosen = options.find((option) => keyOf(option) === choice) ?? options[0] ?? null;

  const onAdd = useCallback(async () => {
    if (target === null || chosen === null) {
      return;
    }
    setBusy(true);
    try {
      // `end` says which way the sentence runs, so the row is written in the direction the
      // writer chose rather than being silently reversed to fit the vocabulary.
      const forward = chosen.end === LINK_ENDS.from;
      await createLink({
        from_entry: forward ? entry.id : target.id,
        relation: chosen.relation.relation,
        to_entry: forward ? target.id : entry.id,
        since: since.trim() === '' ? null : since.trim(),
        until: until.trim() === '' ? null : until.trim(),
      });
      setTargetId('');
      setChoice('');
      setSince('');
      setUntil('');
      onChanged();
    } catch (failure: unknown) {
      push(`Could not add that link — ${describeFailure(failure)}`, 'error');
    } finally {
      setBusy(false);
    }
  }, [chosen, createLink, entry.id, onChanged, push, since, target, until]);

  const onDelete = useCallback(
    async (linkId: string) => {
      setBusy(true);
      try {
        await deleteLink(linkId);
        onChanged();
      } catch (failure: unknown) {
        push(`Could not remove that link — ${describeFailure(failure)}`, 'error');
      } finally {
        setBusy(false);
      }
    },
    [deleteLink, onChanged, push],
  );

  const onSaveBounds = useCallback(
    async (linkId: string, nextSince: string, nextUntil: string) => {
      setBusy(true);
      try {
        await patchLink(linkId, {
          since: nextSince.trim() === '' ? null : nextSince.trim(),
          until: nextUntil.trim() === '' ? null : nextUntil.trim(),
        });
        setEditing(null);
        onChanged();
      } catch (failure: unknown) {
        push(`Could not change those bounds — ${describeFailure(failure)}`, 'error');
      } finally {
        setBusy(false);
      }
    },
    [onChanged, patchLink, push],
  );

  return (
    <section className="entry-links" aria-label="Links">
      <h4>Links</h4>

      {links.length === 0 && <p className="panel-placeholder">No links yet.</p>}

      <ul className="entry-link-list">
        {links.map((view) => (
          <li key={view.link.id} className="entry-link">
            <p className="entry-link-sentence">
              <span className="entry-link-relation">{view.label}</span>{' '}
              <button type="button" className="entry-link-other" onClick={() => onOpen(view.other_id)}>
                {view.other_name}
              </button>{' '}
              <span className="entry-link-kind">{kindLabel(schema, view.other_kind)}</span>
            </p>
            {(view.link.since || view.link.until) && editing !== view.link.id && (
              <p className="entry-link-bounds">
                {view.link.since && <span>from {view.link.since}</span>}
                {view.link.until && <span>until {view.link.until}</span>}
              </p>
            )}
            {editing === view.link.id ? (
              <BoundsEditor
                since={view.link.since ?? ''}
                until={view.link.until ?? ''}
                busy={busy}
                onSave={(nextSince, nextUntil) =>
                  void onSaveBounds(view.link.id, nextSince, nextUntil)
                }
                onCancel={() => setEditing(null)}
              />
            ) : (
              <div className="entry-link-actions">
                <button
                  type="button"
                  disabled={busy}
                  aria-label={`Change when ${view.label} ${view.other_name} holds`}
                  onClick={() => setEditing(view.link.id)}
                >
                  When
                </button>
                <button
                  type="button"
                  disabled={busy}
                  aria-label={`Remove ${view.label} ${view.other_name}`}
                  onClick={() => void onDelete(view.link.id)}
                >
                  Remove
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>

      <form
        className="entry-link-add"
        onSubmit={(event) => {
          event.preventDefault();
          void onAdd();
        }}
      >
        <label htmlFor="link-target">Link to</label>
        <select
          id="link-target"
          value={targetId}
          disabled={busy}
          onChange={(event) => {
            setTargetId(event.target.value);
            setChoice('');
          }}
        >
          <option value="">Choose an entry…</option>
          {candidates.map((other) => (
            <option key={other.id} value={other.id}>
              {other.name} ({kindLabel(schema, other.kind)})
            </option>
          ))}
        </select>

        {target !== null && options.length === 0 && (
          <p className="entry-link-none" role="status">
            Nothing in the vocabulary joins a {kindLabel(schema, entry.kind).toLowerCase()} to a{' '}
            {kindLabel(schema, target.kind).toLowerCase()}.
          </p>
        )}

        {options.length > 0 && (
          <>
            <label htmlFor="link-relation">Relation</label>
            <select
              id="link-relation"
              value={chosen === null ? '' : keyOf(chosen)}
              disabled={busy}
              onChange={(event) => setChoice(event.target.value)}
            >
              {options.map((option) => (
                <option key={keyOf(option)} value={keyOf(option)}>
                  {option.label}
                </option>
              ))}
            </select>

            <div className="entry-link-bounds-inputs">
              <input
                type="text"
                aria-label="From (story time)"
                placeholder="from…"
                value={since}
                disabled={busy}
                onChange={(event) => setSince(event.target.value)}
              />
              <input
                type="text"
                aria-label="Until (story time)"
                placeholder="until…"
                value={until}
                disabled={busy}
                onChange={(event) => setUntil(event.target.value)}
              />
            </div>

            <button type="submit" disabled={busy || target === null}>
              Add link
            </button>
          </>
        )}
      </form>
    </section>
  );
}

interface BoundsEditorProps {
  since: string;
  until: string;
  busy: boolean;
  onSave: (since: string, until: string) => void;
  onCancel: () => void;
}

function BoundsEditor({ since, until, busy, onSave, onCancel }: BoundsEditorProps) {
  const [nextSince, setNextSince] = useState(since);
  const [nextUntil, setNextUntil] = useState(until);
  return (
    <div className="entry-link-bounds-inputs">
      <input
        type="text"
        aria-label="From (story time)"
        value={nextSince}
        disabled={busy}
        onChange={(event) => setNextSince(event.target.value)}
      />
      <input
        type="text"
        aria-label="Until (story time)"
        value={nextUntil}
        disabled={busy}
        onChange={(event) => setNextUntil(event.target.value)}
      />
      {/* Named explicitly: the entry form's own Save is on the same screen, and two controls
          called "Save" is a screen reader with no way to tell a record from a bound. */}
      <button
        type="button"
        disabled={busy}
        aria-label="Save when this link holds"
        onClick={() => onSave(nextSince, nextUntil)}
      >
        Save
      </button>
      <button
        type="button"
        disabled={busy}
        aria-label="Stop changing when this link holds"
        onClick={onCancel}
      >
        Cancel
      </button>
    </div>
  );
}

/** A relation and the direction it would run in, as one selectable value. */
function keyOf(option: RelationOption): string {
  return `${option.relation.relation}:${option.end}`;
}
