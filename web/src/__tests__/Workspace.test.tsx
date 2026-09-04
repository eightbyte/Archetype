/**
 * P1-9 — the three regions, their dividers, and what survives a reload.
 *
 * The divider tests are all keyboard: jsdom has no layout engine, so a pointer drag there would
 * be testing arithmetic against a zero-sized rectangle. The keyboard path is also the one that
 * is easy to leave out and that P1-9 names explicitly, so it is the one held down by tests.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import { App } from '../App';
import { STORAGE_KEYS } from '../state/persistence';
import { INITIAL_UI_STATE, MAX_PANE_WIDTH, MIN_PANE_WIDTH, PANE_STEP } from '../state/uiReducer';
import { Workspace } from '../shell/Workspace';
import { FakeApiClient } from './fakes/fakeApiClient';
import { Harness } from './harness';

function workspace(client: FakeApiClient, projectId: string) {
  return render(
    <Harness client={client} projectId={projectId}>
      <Workspace onLeaveProject={() => {}} />
    </Harness>,
  );
}

async function readyWorkspace() {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  workspace(client, projectId);
  await screen.findByRole('heading', { name: 'The Long Road' });
  return { client, projectId };
}

describe('the three regions', () => {
  test('all three are present, with the agent panel holding its place for Phase 4', async () => {
    await readyWorkspace();

    expect(screen.getByRole('region', { name: 'Outline' })).toBeDefined();
    expect(screen.getByRole('region', { name: 'Manuscript' })).toBeDefined();
    const agent = screen.getByRole('region', { name: 'Assistant' });
    expect(within(agent).getByText(/arrives in Phase 4/)).toBeDefined();
  });

  test('the outline panel offers its five tabs, two of which say when they arrive', async () => {
    const user = userEvent.setup();
    await readyWorkspace();

    // The tab strip was fixed at five in P1-9 so that it would never be re-measured. Marks
    // filled one in Phase 2 (phase-2-plan section 2, ruling 6) and Bible fills another in
    // Phase 3 (P3-12); Timeline and Characters are still placeholders naming Phase 8.
    const tabs = screen.getAllByRole('tab').map((tab) => tab.textContent);
    expect(tabs).toEqual(['Contents', 'Marks', 'Timeline', 'Characters', 'Bible']);

    await user.click(screen.getByRole('tab', { name: 'Timeline' }));
    expect(screen.getByRole('tabpanel').textContent).toContain('Phase 8');

    await user.click(screen.getByRole('tab', { name: 'Bible' }));
    expect(screen.getByRole('tabpanel').textContent).not.toContain('is built in Phase');
  });
});

describe('the dividers', () => {
  test('are reachable and announce the width they control', async () => {
    await readyWorkspace();

    const divider = screen.getByRole('separator', { name: 'Outline panel width' });
    expect(divider.getAttribute('aria-valuenow')).toBe(String(INITIAL_UI_STATE.outlineWidth));
    expect(divider.getAttribute('aria-orientation')).toBe('vertical');
    expect(divider.tabIndex).toBe(0);
  });

  test('arrow keys resize the pane they belong to', async () => {
    const user = userEvent.setup();
    await readyWorkspace();

    const divider = screen.getByRole('separator', { name: 'Outline panel width' });
    divider.focus();
    await user.keyboard('{ArrowRight}');

    expect(divider.getAttribute('aria-valuenow')).toBe(
      String(INITIAL_UI_STATE.outlineWidth + PANE_STEP),
    );
  });

  test('a right-hand pane grows when the divider moves left', async () => {
    const user = userEvent.setup();
    await readyWorkspace();

    const divider = screen.getByRole('separator', { name: 'Assistant panel width' });
    divider.focus();
    await user.keyboard('{ArrowLeft}');

    expect(divider.getAttribute('aria-valuenow')).toBe(
      String(INITIAL_UI_STATE.agentWidth + PANE_STEP),
    );
  });

  test('Home and End go to the narrowest and widest', async () => {
    const user = userEvent.setup();
    await readyWorkspace();

    const divider = screen.getByRole('separator', { name: 'Outline panel width' });
    divider.focus();
    await user.keyboard('{Home}');
    expect(divider.getAttribute('aria-valuenow')).toBe(String(MIN_PANE_WIDTH));

    await user.keyboard('{End}');
    expect(divider.getAttribute('aria-valuenow')).toBe(String(MAX_PANE_WIDTH));
  });

  test('Enter collapses the pane to a rail that can bring it back', async () => {
    const user = userEvent.setup();
    await readyWorkspace();

    const divider = screen.getByRole('separator', { name: 'Outline panel width' });
    divider.focus();
    await user.keyboard('{Enter}');

    expect(screen.queryByRole('tablist')).toBeNull();
    expect(divider.getAttribute('aria-valuetext')).toBe('collapsed');

    await user.click(screen.getByRole('button', { name: 'Show the outline panel' }));
    expect(screen.getByRole('tablist')).toBeDefined();
  });
});

describe('what survives a reload', () => {
  test('pane widths, collapse, and the active tab are persisted and restored', async () => {
    const user = userEvent.setup();
    const client = new FakeApiClient();
    const projectId = client.seedProject('The Long Road');

    const first = workspace(client, projectId);
    await screen.findByRole('heading', { name: 'The Long Road' });

    const divider = screen.getByRole('separator', { name: 'Outline panel width' });
    divider.focus();
    await user.keyboard('{End}');
    await user.click(screen.getByRole('tab', { name: 'Timeline' }));
    await user.keyboard('{Tab}');
    screen.getByRole('separator', { name: 'Assistant panel width' }).focus();
    await user.keyboard('{Enter}');

    // The reload: everything React knows is thrown away, and only storage carries over.
    first.unmount();
    workspace(client, projectId);
    await screen.findByRole('heading', { name: 'The Long Road' });

    expect(
      screen.getByRole('separator', { name: 'Outline panel width' }).getAttribute('aria-valuenow'),
    ).toBe(String(MAX_PANE_WIDTH));
    expect(screen.getByRole('tab', { name: 'Timeline' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('button', { name: 'Show the assistant panel' })).toBeDefined();
  });

  test('the layout is written under one namespaced key', async () => {
    const user = userEvent.setup();
    await readyWorkspace();

    const divider = screen.getByRole('separator', { name: 'Outline panel width' });
    divider.focus();
    await user.keyboard('{Home}');

    const stored: unknown = JSON.parse(localStorage.getItem(STORAGE_KEYS.ui) ?? 'null');
    expect(stored).toMatchObject({ outlineWidth: MIN_PANE_WIDTH });
  });

  test('a layout that cannot be read is a default layout, not a broken workspace', async () => {
    localStorage.setItem(STORAGE_KEYS.ui, 'not json at all');
    await readyWorkspace();

    expect(
      screen.getByRole('separator', { name: 'Outline panel width' }).getAttribute('aria-valuenow'),
    ).toBe(String(INITIAL_UI_STATE.outlineWidth));
  });
});

describe('leaving the project', () => {
  test('the header offers a way back to the picker', async () => {
    const user = userEvent.setup();
    const client = new FakeApiClient();
    const projectId = client.seedProject('The Long Road');

    render(<App client={client} initialProjectId={projectId} />);
    await screen.findByRole('heading', { name: 'The Long Road' });

    await user.click(screen.getByRole('button', { name: '← Projects' }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Archetype' })).toBeDefined();
    });
  });

  test('a reload lands back in the project that was open', async () => {
    const user = userEvent.setup();
    const client = new FakeApiClient({ projects: ['The Long Road'] });

    // Opened the way a writer opens it — through the picker, which is what records it.
    const first = render(<App client={client} />);
    await user.click(await screen.findByRole('button', { name: /The Long Road/ }));
    await screen.findByRole('heading', { name: 'The Long Road' });
    first.unmount();

    render(<App client={client} />);
    await screen.findByRole('heading', { name: 'The Long Road' });
  });

  test('going back to the picker means the next reload starts there', async () => {
    const user = userEvent.setup();
    const client = new FakeApiClient({ projects: ['The Long Road'] });

    const first = render(<App client={client} />);
    await user.click(await screen.findByRole('button', { name: /The Long Road/ }));
    await screen.findByRole('heading', { name: 'The Long Road' });
    await user.click(screen.getByRole('button', { name: '← Projects' }));
    await screen.findByRole('heading', { name: 'Archetype' });
    first.unmount();

    render(<App client={client} />);
    await screen.findByRole('heading', { name: 'Archetype' });
  });

  test('the project just opened is offered as a recent shortcut next time', async () => {
    const user = userEvent.setup();
    const client = new FakeApiClient({ projects: ['The Long Road'] });

    const first = render(<App client={client} />);
    await user.click(await screen.findByRole('button', { name: /The Long Road/ }));
    await screen.findByRole('heading', { name: 'The Long Road' });
    await user.click(screen.getByRole('button', { name: '← Projects' }));
    first.unmount();

    render(<App client={client} />);
    const recent = await screen.findByRole('navigation', { name: 'Recently opened' });
    expect(within(recent).getByRole('button', { name: 'The Long Road' })).toBeDefined();
  });
});
