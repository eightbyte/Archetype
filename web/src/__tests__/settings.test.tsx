/**
 * P4-15 — the settings screen, and the one thing it must never do (D8, D34).
 *
 * The headline assertion is a negative: **no key reaches the browser, and there is no way to put
 * one there.** `GET /api/settings` reports *whether* a key is present, per provider, and never its
 * value; there is no input for one on this screen because there is no route that would accept it.
 * The backend half of the same rule walks the whole API surface with a key configured and
 * searches every response body for its value (`test_provider_registry.py`).
 *
 * The second is the phase's own acceptance bar: **swapping providers is a settings change with no
 * code change.** Here that is a `PATCH` carrying one field; § 8 does it by hand against two real
 * providers, which is the half a suite cannot do.
 *
 * The screen renders the **real** served shape: the fake reads the contract fixture, so this is
 * the field list, the writable list, and the provider status the server actually sends.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import { ApiError } from '../api';
import { Workspace } from '../shell/Workspace';
import { FakeApiClient } from './fakes/fakeApiClient';
import { FakeChatSocketFactory } from './fakes/fakeChatSocket';
import { Harness, prose } from './harness';

async function open(): Promise<{ panel: HTMLElement; client: FakeApiClient }> {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  const [documentId] = client.documentIdsOf(projectId);
  await client.saveDocumentContent(documentId!, prose('The harbour was grey.'), 1);

  render(
    <Harness
      client={client}
      projectId={projectId}
      socketFactory={new FakeChatSocketFactory().create}
      scheduler={{ delayMs: 60_000 }}
    >
      <Workspace onLeaveProject={() => {}} />
    </Harness>,
  );
  const panel = screen.getByRole('region', { name: 'Assistant' });
  await within(panel).findByRole('button', { name: 'New conversation' });
  await userEvent.setup().click(within(panel).getByRole('button', { name: 'Settings' }));
  await within(panel).findByLabelText('Provider');
  return { panel, client };
}

describe('what the screen shows', () => {
  test('every writable setting, rendered from the server’s own list', async () => {
    const { panel } = await open();

    // `writable` is served rather than assumed, so a field that stops being writable stops being
    // editable in the same commit.
    expect(within(panel).getByLabelText('Provider')).toBeDefined();
    expect(within(panel).getByLabelText('Model')).toBeDefined();
    expect(within(panel).getByLabelText('Answer limit')).toBeDefined();
    expect(within(panel).getByLabelText('Context budget')).toBeDefined();
    expect(within(panel).getByLabelText('Streaming')).toBeDefined();
  });

  test('the provider picker offers only providers this build has an adapter for', async () => {
    const { panel } = await open();

    const options = [...within(panel).getByLabelText('Provider').querySelectorAll('option')].map(
      (option) => option.textContent,
    );
    // `known_providers` is the registry's own answer. A picker that offered a name with no
    // adapter would be offering a choice that can never work.
    expect(options).toEqual(['anthropic', 'openai']);
  });

  test('whether a key is present, per provider — and never a key', async () => {
    const { panel } = await open();

    // The fixture has no key set for either provider, which is what a clean checkout looks like.
    expect(within(panel).getAllByText('no key')).toHaveLength(2);
    expect(within(panel).getByText('ARCHETYPE_ANTHROPIC_API_KEY')).toBeDefined();
    expect(within(panel).getByText('ARCHETYPE_OPENAI_API_KEY')).toBeDefined();
    // There is no input for a key, because there is no route that would accept one.
    expect(within(panel).queryByLabelText(/key/i)).toBeNull();
    expect(within(panel).getByText(/never shown here and can never be set here/)).toBeDefined();
  });

  test('it says why the assistant is not ready, in the registry’s own words', async () => {
    const { panel } = await open();

    // The same sentence the chat panel gets as `provider_unconfigured`: one condition, one
    // wording, so the two surfaces cannot disagree about the same thing.
    expect(within(panel).getByText(/Not ready/)).toBeDefined();
    expect(within(panel).getByText(/no API key is set for anthropic/)).toBeDefined();
  });

  test('the process-level settings are shown and are not editable here', async () => {
    const { panel } = await open();

    // `data_dir`, `host`, `port`, `log_level`, and `web_dist` are resolved once at startup: a
    // route that changed one would leave a running server whose settings describe something it
    // is not doing (deviation `C4`). They stay readable.
    expect(within(panel).getByText('data_dir')).toBeDefined();
    expect(within(panel).getByText('log_level')).toBeDefined();
    expect(within(panel).queryByLabelText('data_dir')).toBeNull();
    expect(within(panel).getByText(/and a restart/)).toBeDefined();
  });
});

describe('changing one', () => {
  test('swapping the provider is a `PATCH` carrying one field', async () => {
    const user = userEvent.setup();
    const { panel, client } = await open();

    await user.selectOptions(within(panel).getByLabelText('Provider'), 'openai');
    await user.click(within(panel).getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(client.calls).toContain('patchSettings'));
    // No reload and no restart: the provider is built from a factory on every request, so this
    // changes what the *next* question is answered by.
    expect(await screen.findByText(/in force for the next question/)).toBeDefined();
    await waitFor(() => {
      // The draft is cleared and the screen redraws from the **response**, which reports what is
      // actually in force — not what was written. These settings layer defaults < config.yaml <
      // ARCHETYPE_*, and this route writes the middle one, so a field also set in the environment
      // is written and then overridden. Reading the answer back is how a writer finds that out.
      const picker = within(panel).getByLabelText('Provider') as HTMLSelectElement;
      expect(picker.value).toBe('openai');
      expect(within(panel).getByRole('button', { name: 'Save' }).hasAttribute('disabled')).toBe(
        true,
      );
    });
  });

  test('nothing is sent until something is changed, and Revert throws the draft away', async () => {
    const user = userEvent.setup();
    const { panel, client } = await open();

    expect(within(panel).getByRole('button', { name: 'Save' }).hasAttribute('disabled')).toBe(true);

    await user.selectOptions(within(panel).getByLabelText('Provider'), 'openai');
    expect(within(panel).getByRole('button', { name: 'Save' }).hasAttribute('disabled')).toBe(
      false,
    );

    await user.click(within(panel).getByRole('button', { name: 'Revert' }));

    expect(within(panel).getByRole('button', { name: 'Save' }).hasAttribute('disabled')).toBe(true);
    expect(client.calls).not.toContain('patchSettings');
  });

  test('a refusal is reported and the screen stays usable', async () => {
    const user = userEvent.setup();
    const { panel, client } = await open();
    // The validator is the server's — `SettingsPatchIn` refuses a secret by name and a provider
    // this build has no adapter for. A test that needs a refusal stages one.
    client.failNext(
      'patchSettings',
      new ApiError(422, 'validation_error', 'there is no adapter for a provider called “x”', null),
    );

    await user.selectOptions(within(panel).getByLabelText('Provider'), 'openai');
    await user.click(within(panel).getByRole('button', { name: 'Save' }));

    expect(await screen.findByText(/Could not save the settings/)).toBeDefined();
    expect(within(panel).getByLabelText('Provider')).toBeDefined();
  });
});

describe('getting back', () => {
  test('the settings are a view of the panel, not a place you get stuck in', async () => {
    const user = userEvent.setup();
    const { panel } = await open();

    await user.click(within(panel).getByRole('button', { name: 'Back' }));

    expect(within(panel).getByRole('button', { name: 'New conversation' })).toBeDefined();
  });
});
