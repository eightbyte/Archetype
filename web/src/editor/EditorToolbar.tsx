/**
 * The formatting controls (P1-10).
 *
 * One button per thing the schema can express, and no more — the toolbar is the closed list made
 * visible. A button that is on shows `aria-pressed`, so what is active is announced rather than
 * only shaded, and every control keeps its keyboard shortcut in the tooltip because that is how
 * a writer will actually reach it.
 */

import type { Editor } from '@tiptap/react';
import { HEADING_LEVELS } from './extensions';
import type { HeadingLevel } from './extensions';

export interface EditorToolbarProps {
  /** Null until TipTap has built the view, which it does after the first render. */
  editor: Editor | null;
}

export function EditorToolbar({ editor }: EditorToolbarProps) {
  const disabled = editor === null;

  return (
    <div className="toolbar" role="toolbar" aria-label="Formatting">
      <div className="toolbar-group">
        <Command
          editor={editor}
          label="Bold"
          hint="Bold (Ctrl+B)"
          active={editor?.isActive('bold') ?? false}
          run={(instance) => instance.chain().focus().toggleBold().run()}
        />
        <Command
          editor={editor}
          label="Italic"
          hint="Italic (Ctrl+I)"
          active={editor?.isActive('italic') ?? false}
          run={(instance) => instance.chain().focus().toggleItalic().run()}
        />
      </div>

      <div className="toolbar-group">
        <Command
          editor={editor}
          label="Body"
          hint="Body text (Ctrl+Alt+0)"
          active={editor?.isActive('paragraph') ?? false}
          run={(instance) => instance.chain().focus().setParagraph().run()}
        />
        {HEADING_LEVELS.map((level: HeadingLevel) => (
          <Command
            key={level}
            editor={editor}
            label={`H${level}`}
            hint={`Heading ${level} (Ctrl+Alt+${level})`}
            active={editor?.isActive('heading', { level }) ?? false}
            run={(instance) => instance.chain().focus().toggleHeading({ level }).run()}
          />
        ))}
      </div>

      <div className="toolbar-group">
        <Command
          editor={editor}
          label="Bulleted"
          hint="Bulleted list"
          active={editor?.isActive('bulletList') ?? false}
          run={(instance) => instance.chain().focus().toggleBulletList().run()}
        />
        <Command
          editor={editor}
          label="Numbered"
          hint="Numbered list"
          active={editor?.isActive('orderedList') ?? false}
          run={(instance) => instance.chain().focus().toggleOrderedList().run()}
        />
        <Command
          editor={editor}
          label="Quote"
          hint="Block quotation"
          active={editor?.isActive('blockquote') ?? false}
          run={(instance) => instance.chain().focus().toggleBlockquote().run()}
        />
        <Command
          editor={editor}
          label="Scene break"
          hint="Scene break"
          active={false}
          run={(instance) => instance.chain().focus().setHorizontalRule().run()}
        />
      </div>

      <div className="toolbar-group">
        <button
          type="button"
          title="Undo (Ctrl+Z)"
          disabled={disabled || !editor.can().undo()}
          onClick={() => editor?.chain().focus().undo().run()}
        >
          Undo
        </button>
        <button
          type="button"
          title="Redo (Ctrl+Shift+Z)"
          disabled={disabled || !editor.can().redo()}
          onClick={() => editor?.chain().focus().redo().run()}
        >
          Redo
        </button>
      </div>
    </div>
  );
}

interface CommandProps {
  editor: Editor | null;
  label: string;
  hint: string;
  active: boolean;
  run: (editor: Editor) => void;
}

function Command({ editor, label, hint, active, run }: CommandProps) {
  return (
    <button
      type="button"
      title={hint}
      aria-pressed={active}
      disabled={editor === null}
      onClick={() => {
        if (editor) {
          run(editor);
        }
      }}
    >
      {label}
    </button>
  );
}
