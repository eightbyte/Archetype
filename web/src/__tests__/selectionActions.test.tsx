/**
 * P2-9, P2-10 — the control that appears over a selection.
 *
 * It runs against a real TipTap editor built here rather than the app's, for one reason: jsdom
 * has no native editing, so a text selection cannot be made through the DOM the way a person
 * makes one. The selection is set through ProseMirror's own command instead, which is the same
 * state the control reads either way — what is being tested is what it does with a selection,
 * not how the selection got there.
 *
 * The range it reports is the whole contract of P2-9's create path: the client sends *where*, and
 * the server derives *what* from the text it holds. A control that reported the wrong range would
 * anchor the wrong words, and nothing downstream could tell.
 *
 * Phase 3 added a third action to the same control: *Add to bible* (P3-14), which anchors the
 * selection **and** makes an entry out of it. It is covered here for the same reason the other two
 * are — this is the half of the gesture a real editor can be held to — and its other half, what
 * happens below the call, is in `entryLinks.test.tsx`.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditorContent, useEditor } from '@tiptap/react';
import { useState } from 'react';
import { describe, expect, test, vi } from 'vitest';
import { EDITOR_EXTENSIONS } from '../editor/extensions';
import { SelectionActions } from '../editor/SelectionActions';
import type { BibleDraft, SelectionRange } from '../editor/SelectionActions';
import type { KindDefinition } from '../api/types';

interface ProbeProps {
  onMark?: (range: SelectionRange) => void;
  onRelink?: (range: SelectionRange) => void;
  onCancelRelink?: () => void;
  relinking?: { anchorId: string; description: string } | null;
  busy?: boolean;
  /** The served definition's kinds. Empty by default: P2-9's tests are about marking. */
  kinds?: KindDefinition[];
  onAddToBible?: (range: SelectionRange, draft: BibleDraft) => void;
}

/** A real editor over one paragraph, with the control beside it and a way to select text. */
function Probe({
  onMark,
  onRelink,
  onCancelRelink,
  relinking,
  busy,
  kinds,
  onAddToBible,
}: ProbeProps) {
  const [ready, setReady] = useState(false);
  const editor = useEditor({
    extensions: EDITOR_EXTENSIONS,
    content: {
      type: 'doc',
      content: [
        { type: 'paragraph', content: [{ type: 'text', text: 'The harbour was grey.' }] },
      ],
    },
    onCreate: () => setReady(true),
  });

  return (
    <div>
      <EditorContent editor={editor} />
      {/* The test's stand-in for dragging across words with a mouse. */}
      <button
        type="button"
        onClick={() => editor?.commands.setTextSelection({ from: 5, to: 16 })}
        disabled={!ready}
      >
        Select the passage
      </button>
      <button type="button" onClick={() => editor?.commands.setTextSelection({ from: 5, to: 5 })}>
        Select nothing
      </button>
      <SelectionActions
        editor={editor}
        onMark={onMark ?? (() => {})}
        relinking={relinking ?? null}
        onRelink={onRelink ?? (() => {})}
        onCancelRelink={onCancelRelink ?? (() => {})}
        busy={busy ?? false}
        kinds={kinds ?? []}
        onAddToBible={onAddToBible ?? (() => {})}
      />
    </div>
  );
}

async function select(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  const control = await screen.findByRole('button', { name: 'Select the passage' });
  await waitFor(() => expect(control.hasAttribute('disabled')).toBe(false));
  await user.click(control);
}

describe('marking a passage', () => {
  test('there is no control until something is selected', () => {
    render(<Probe />);

    expect(screen.queryByRole('button', { name: 'Mark passage' })).toBeNull();
  });

  test('selecting text offers to mark it, and reports the range that was selected', async () => {
    const user = userEvent.setup();
    const onMark = vi.fn();
    render(<Probe onMark={onMark} />);

    await select(user);
    await user.click(await screen.findByRole('button', { name: 'Mark passage' }));

    expect(onMark).toHaveBeenCalledWith({ from: 5, to: 16 });
  });

  test('the control goes away when the selection collapses', async () => {
    const user = userEvent.setup();
    render(<Probe />);

    await select(user);
    await screen.findByRole('button', { name: 'Mark passage' });

    await user.click(screen.getByRole('button', { name: 'Select nothing' }));

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Mark passage' })).toBeNull();
    });
  });

  test('it cannot be pressed twice while a request is in the air', async () => {
    const user = userEvent.setup();
    const onMark = vi.fn();
    render(<Probe onMark={onMark} busy />);

    await select(user);
    const marking = await screen.findByRole('button', { name: 'Marking…' });

    expect(marking.hasAttribute('disabled')).toBe(true);
  });
});

describe('re-linking by hand (P2-10)', () => {
  const RELINKING = { anchorId: 'anc_1', description: '“the harbour”' };

  test('while armed, the same selection offers a re-link instead of a new mark', async () => {
    const user = userEvent.setup();
    const onRelink = vi.fn();
    const onMark = vi.fn();
    render(<Probe relinking={RELINKING} onRelink={onRelink} onMark={onMark} />);

    await select(user);
    await user.click(await screen.findByRole('button', { name: 'Re-link here' }));

    expect(onRelink).toHaveBeenCalledWith({ from: 5, to: 16 });
    expect(onMark).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Mark passage' })).toBeNull();
  });

  test('with nothing selected it still says what it is waiting for, and offers a way out', async () => {
    const user = userEvent.setup();
    const onCancelRelink = vi.fn();
    render(<Probe relinking={RELINKING} onCancelRelink={onCancelRelink} />);

    expect(screen.getByRole('status').textContent).toContain('“the harbour”');

    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(onCancelRelink).toHaveBeenCalled();
  });
});

describe('adding to the bible (P3-14)', () => {
  /** Two kinds from the served definition, which is where the picker's contents come from. */
  const KINDS: KindDefinition[] = [
    { kind: 'character', label: 'Character', plural: 'Characters', fields: [] },
    { kind: 'place', label: 'Place', plural: 'Places', fields: [] },
  ];

  test('is not offered at all until the definition has arrived', async () => {
    // An empty picker is worse than no control: it offers a choice that cannot be made.
    const user = userEvent.setup();
    render(<Probe />);

    await select(user);

    expect(await screen.findByRole('button', { name: 'Mark passage' })).toBeDefined();
    expect(screen.queryByRole('button', { name: 'Add to bible' })).toBeNull();
  });

  test('asks for a kind and a name, and reports the range that was selected', async () => {
    const user = userEvent.setup();
    const onAddToBible = vi.fn();
    render(<Probe kinds={KINDS} onAddToBible={onAddToBible} />);

    await select(user);
    await user.click(await screen.findByRole('button', { name: 'Add to bible' }));
    await user.selectOptions(screen.getByLabelText('Kind'), 'place');
    await user.type(screen.getByLabelText('Name'), 'The Quay');
    await user.click(screen.getByRole('button', { name: 'Add to bible' }));

    // The range is the whole contract of the create path: the client sends *where*, and the
    // server derives *what* from the text it holds.
    expect(onAddToBible).toHaveBeenCalledWith(
      { from: 5, to: 16 },
      { kind: 'place', name: 'The Quay' },
    );
  });

  test('the name is not guessed from the selected words', async () => {
    // A passage that says "the woman at the rail" is not a character called *the woman at the
    // rail*; the selection becomes the citation, which is the part the server derives.
    const user = userEvent.setup();
    render(<Probe kinds={KINDS} />);

    await select(user);
    await user.click(await screen.findByRole('button', { name: 'Add to bible' }));

    expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('');
  });

  test('nothing is sent without a name', async () => {
    const user = userEvent.setup();
    const onAddToBible = vi.fn();
    render(<Probe kinds={KINDS} onAddToBible={onAddToBible} />);

    await select(user);
    await user.click(await screen.findByRole('button', { name: 'Add to bible' }));
    await user.click(screen.getByRole('button', { name: 'Add to bible' }));

    expect(onAddToBible).not.toHaveBeenCalled();
  });

  test('the range is frozen when the form opens, so typing a name cannot move it', async () => {
    // Typing into the name field takes focus out of the editor; a stray transaction must not
    // move the selection under the writer's hands.
    const user = userEvent.setup();
    const onAddToBible = vi.fn();
    render(<Probe kinds={KINDS} onAddToBible={onAddToBible} />);

    await select(user);
    await user.click(await screen.findByRole('button', { name: 'Add to bible' }));
    await user.click(screen.getByRole('button', { name: 'Select nothing' }));
    await user.type(screen.getByLabelText('Name'), 'Marlow');
    await user.click(screen.getByRole('button', { name: 'Add to bible' }));

    expect(onAddToBible).toHaveBeenCalledWith(
      { from: 5, to: 16 },
      { kind: 'character', name: 'Marlow' },
    );
  });

  test('cancelling sends nothing and puts the two ordinary actions back', async () => {
    const user = userEvent.setup();
    const onAddToBible = vi.fn();
    render(<Probe kinds={KINDS} onAddToBible={onAddToBible} />);

    await select(user);
    await user.click(await screen.findByRole('button', { name: 'Add to bible' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(onAddToBible).not.toHaveBeenCalled();
    expect(await screen.findByRole('button', { name: 'Mark passage' })).toBeDefined();
  });

  test('a re-link in progress offers neither — one repair at a time', async () => {
    const user = userEvent.setup();
    render(<Probe kinds={KINDS} relinking={{ anchorId: 'anc_1', description: '“the harbour”' }} />);

    await select(user);
    await screen.findByRole('button', { name: 'Re-link here' });

    expect(screen.queryByRole('button', { name: 'Add to bible' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Mark passage' })).toBeNull();
  });
});
