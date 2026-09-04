/**
 * P2-13, P2-14 — Markdown in and out, from the Contents tab.
 *
 * The syntax, the escaping, and the round trip are the server's, asserted against the corpus in
 * `server/tests/fixtures/markdown/cases.json` and over HTTP in `test_markdown_routes.py`. **The
 * fake API client has no Markdown parser and must never grow one**, for the same reason it has
 * no anchor resolver (C4): a second parser with neither a specification nor a corpus behind it
 * would make every test here assert against a rule nobody wrote down. So an import creates what
 * `stageImport` says it creates.
 *
 * What is left, and what these tests are for, is the client's actual share of the work: an
 * export offered as a link the browser can save rather than as bytes held in memory; a form that
 * collects the file, the mode, and the name, and sends exactly those; the chapters arriving in
 * project state without a reload; and — the one that matters — the report of what the import
 * could not keep being *shown*, because an import that silently edited somebody's file is the
 * friendly-sounding version of data loss.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import { ApiError, ERROR_CODES } from '../api';
import { Workspace } from '../shell/Workspace';
import { FakeApiClient } from './fakes/fakeApiClient';
import { Harness, prose } from './harness';

interface Seeded {
  client: FakeApiClient;
  projectId: string;
  ids: string[];
}

async function mount(): Promise<Seeded> {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  const ids = [...client.documentIdsOf(projectId)];
  ids.push((await client.createDocument(projectId, 'Departure')).id);
  for (const id of ids) {
    await client.saveDocumentContent(id, prose('The harbour was grey.'), 1);
  }

  render(
    <Harness client={client} projectId={projectId} scheduler={{ delayMs: 60_000 }}>
      <Workspace onLeaveProject={() => {}} />
    </Harness>,
  );
  await waitFor(() => {
    if (!document.querySelector('.manuscript')) {
      throw new Error('the editor has not mounted yet');
    }
  });
  return { client, projectId, ids };
}

function toc(): HTMLElement {
  return screen.getByRole('tabpanel');
}

function titles(): string[] {
  return [...toc().querySelectorAll('.toc-chapter-title')].map(
    (element) => element.textContent ?? '',
  );
}

/** Open the import form and put Markdown in the box. */
async function openImport(user: ReturnType<typeof userEvent.setup>, markdown: string) {
  await user.click(screen.getByRole('button', { name: 'Import Markdown…' }));
  await user.type(screen.getByLabelText('Markdown'), markdown);
}

describe('exporting', () => {
  test('a chapter is offered as a link the browser saves, not as bytes held in memory', async () => {
    const { ids } = await mount();

    const link = screen.getByRole('link', { name: 'Departure: export as Markdown' });

    expect(link.getAttribute('href')).toBe(`/api/documents/${ids[1]}/markdown`);
    expect(link.hasAttribute('download')).toBe(true);
  });

  test('every chapter has one, and the whole manuscript has one', async () => {
    const { projectId } = await mount();

    expect(screen.getAllByRole('link', { name: /export as Markdown$/ })).toHaveLength(2);
    expect(screen.getByRole('link', { name: 'Export manuscript' }).getAttribute('href')).toBe(
      `/api/projects/${projectId}/markdown`,
    );
  });

  test('nothing is fetched to draw them', async () => {
    // The export is served as an attachment (§ 2, ruling 9): the address is the whole client.
    const { client } = await mount();

    expect(client.calls).not.toContain('importMarkdown');
    expect(client.calls.filter((call) => call.includes('arkdown'))).toEqual([]);
  });

  test('the link follows a rename', async () => {
    const user = userEvent.setup();
    await mount();

    await user.click(screen.getByRole('button', { name: 'Departure: rename' }));
    await user.clear(screen.getByLabelText('Departure: new name'));
    await user.type(screen.getByLabelText('Departure: new name'), 'Away{Enter}');

    await waitFor(() => {
      expect(screen.getByRole('link', { name: 'Away: export as Markdown' })).toBeTruthy();
    });
  });
});

describe('importing', () => {
  test('sends what is on screen: the text, the mode, and the name', async () => {
    const user = userEvent.setup();
    const { client, projectId } = await mount();

    await openImport(user, 'Some prose.');
    await user.type(screen.getByLabelText('Chapter name'), 'Ashore');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => {
      expect(client.imports).toEqual([
        { projectId, markdown: 'Some prose.', mode: 'one-chapter', title: 'Ashore' },
      ]);
    });
  });

  test('a chapter left unnamed is named the way any new chapter is', async () => {
    const user = userEvent.setup();
    const { client } = await mount();

    await openImport(user, 'Some prose.');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => {
      expect(client.imports[0]?.title).toBeNull();
    });
  });

  test('the split mode is sent when it is chosen, and carries no name of its own', async () => {
    const user = userEvent.setup();
    const { client } = await mount();

    await openImport(user, '# One');
    await user.click(screen.getByRole('radio', { name: 'A chapter per top-level heading' }));
    await user.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => {
      expect(client.imports[0]?.mode).toBe('split-on-h1');
      expect(client.imports[0]?.title).toBeNull();
    });
  });

  test('the name field belongs to one-chapter mode alone', async () => {
    const user = userEvent.setup();
    await mount();

    await user.click(screen.getByRole('button', { name: 'Import Markdown…' }));
    expect(screen.getByLabelText('Chapter name')).toBeTruthy();

    await user.click(screen.getByRole('radio', { name: 'A chapter per top-level heading' }));

    expect(screen.queryByLabelText('Chapter name')).toBeNull();
  });

  test('the chapters appear in the contents without a reload', async () => {
    const user = userEvent.setup();
    const { client } = await mount();
    client.stageImport({
      chapters: [
        { title: 'Ashore', paragraphs: ['The tide turned.'] },
        { title: 'Inland', paragraphs: ['And kept turning.'] },
      ],
    });

    await openImport(user, '# Ashore\n\n# Inland');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => {
      expect(titles()).toEqual(['Chapter 1', 'Departure', 'Ashore', 'Inland']);
    });
    expect(client.calls.filter((call) => call === 'getProject')).toHaveLength(1);
  });

  test('the first imported chapter is opened, so the writer can see what arrived', async () => {
    const user = userEvent.setup();
    const { client } = await mount();
    client.stageImport({ chapters: [{ title: 'Ashore', paragraphs: ['The tide turned.'] }] });

    await openImport(user, 'The tide turned.');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => {
      expect(document.querySelector('.manuscript')?.textContent).toContain('The tide turned.');
    });
  });

  test('the word counts come from the import, not from a guess', async () => {
    const user = userEvent.setup();
    const { client } = await mount();
    client.stageImport({ chapters: [{ title: 'Ashore', paragraphs: ['One two three four.'] }] });

    await openImport(user, 'One two three four.');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => {
      expect(screen.getByTestId('toc-total').textContent).toContain('3 chapters');
    });
  });

  test('the form closes and empties, so a second import does not resend the first', async () => {
    const user = userEvent.setup();
    await mount();

    await openImport(user, 'Some prose.');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => {
      expect(screen.queryByLabelText('Markdown')).toBeNull();
    });
    await user.click(screen.getByRole('button', { name: 'Import Markdown…' }));
    expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe('');
  });

  test('an empty box cannot be imported', async () => {
    const user = userEvent.setup();
    await mount();

    await user.click(screen.getByRole('button', { name: 'Import Markdown…' }));

    expect((screen.getByRole('button', { name: 'Import' }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  test('cancelling sends nothing', async () => {
    const user = userEvent.setup();
    const { client } = await mount();

    await openImport(user, 'Some prose.');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(client.imports).toEqual([]);
    expect(screen.queryByLabelText('Markdown')).toBeNull();
  });
});

describe('what the import could not keep', () => {
  test('every dropped element is shown, with where it was and what became of it', async () => {
    const user = userEvent.setup();
    const { client } = await mount();
    client.stageImport({
      chapters: [{ title: 'Ashore' }],
      dropped: [
        {
          element: 'code fence',
          line: 3,
          detail: 'the text was kept as a paragraph; the code formatting was not',
        },
        { element: 'link', line: 9, detail: 'the link text was kept; http://x/y was not' },
      ],
    });

    await openImport(user, 'anything');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    const report = await screen.findByRole('status', { name: 'What the import did' });
    expect(within(report).getByText('code fence')).toBeTruthy();
    expect(report.textContent).toContain('line 3');
    expect(report.textContent).toContain('the code formatting was not');
    expect(within(report).getByText('link')).toBeTruthy();
    expect(report.textContent).toContain('line 9');
  });

  test('an import that kept everything says so, rather than saying nothing', async () => {
    const user = userEvent.setup();
    const { client } = await mount();
    client.stageImport({ chapters: [{ title: 'Ashore' }] });

    await openImport(user, 'plain prose');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    const report = await screen.findByRole('status', { name: 'What the import did' });
    expect(report.textContent).toContain('Nothing was left behind');
    expect(report.textContent).toContain('Ashore');
  });

  test('the report stays until it is dismissed', async () => {
    const user = userEvent.setup();
    const { client } = await mount();
    client.stageImport({
      chapters: [{ title: 'Ashore' }],
      dropped: [{ element: 'image', line: 2, detail: 'an image is not part of the manuscript' }],
    });

    await openImport(user, 'anything');
    await user.click(screen.getByRole('button', { name: 'Import' }));
    await screen.findByRole('status', { name: 'What the import did' });

    await user.click(screen.getByRole('button', { name: 'Dismiss report' }));

    expect(screen.queryByRole('status', { name: 'What the import did' })).toBeNull();
  });
});

describe('when the import is refused', () => {
  test('a file too large says so and creates nothing', async () => {
    const user = userEvent.setup();
    const { client } = await mount();
    client.failNext(
      'importMarkdown',
      new ApiError(413, ERROR_CODES.payloadTooLarge, 'that file is 9000000 bytes', null),
    );

    await openImport(user, 'a very large file');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => {
      expect(screen.getByRole('log').textContent).toContain('Could not import that file');
    });
    expect(titles()).toEqual(['Chapter 1', 'Departure']);
  });

  test('the box keeps what was in it, so a refused import is not retyped', async () => {
    const user = userEvent.setup();
    const { client } = await mount();
    client.failNext(
      'importMarkdown',
      new ApiError(413, ERROR_CODES.payloadTooLarge, 'that file is too large', null),
    );

    await openImport(user, 'The words that were refused.');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => {
      expect(screen.getByRole('log').textContent).toContain('Could not import');
    });
    expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe(
      'The words that were refused.',
    );
  });

  test('no report is drawn for an import that did not happen', async () => {
    const user = userEvent.setup();
    const { client } = await mount();
    client.failNext(
      'importMarkdown',
      new ApiError(422, ERROR_CODES.validation, 'that is not a mode', null),
    );

    await openImport(user, 'anything');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => {
      expect(screen.getByRole('log').textContent).toContain('Could not import');
    });
    expect(screen.queryByRole('status', { name: 'What the import did' })).toBeNull();
  });
});
