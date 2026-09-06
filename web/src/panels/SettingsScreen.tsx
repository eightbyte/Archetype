/**
 * The settings screen (P4-15, D34, deviation `C4`).
 *
 * Provider, base URL, model, budgets, the capability flags — and a **key presence indicator that
 * is never a key**. `GET /api/settings` reports *whether* a key is present, per provider, and
 * never its value, its length, or its first characters; there is no input for one on this screen
 * because there is no route that would accept it. An API key comes from the environment, and
 * that is the whole of D8 as D34 narrows it.
 *
 * ## Two lists, and both come from the server
 *
 * `writable` says which fields a `PATCH` may change, and this screen renders **inputs from that
 * list** rather than from one of its own — so a field that stops being writable stops being
 * editable in the same commit. `known_providers` is the registry's own answer about what this
 * build has an adapter for, so the provider picker cannot offer one that can never work.
 *
 * Everything else — the data directory, the host, the port, the log level, the bundle path — is
 * shown and is **not editable here**. Those are resolved once, at startup: the projects directory
 * is scanned from one and the static mount installed from another, so a route that changed one
 * would leave a running server whose settings describe something it is not doing. They change the
 * way they always have, through the environment or the file, and a restart.
 *
 * ## And it takes effect on the next request
 *
 * No reload and no restart. The provider is built from a factory on every request (P4-8), so a
 * `PATCH` here changes what the *next* question is answered by — which is the phase's own
 * acceptance bar: swapping providers is a settings change with no code change.
 */

import { useCallback, useEffect, useState } from 'react';
import type { AppSettings, SettingsDocument, SettingsPatch } from '../api';
import { useChat } from '../state/ChatContext';
import { describeFailure } from '../state/ProjectContext';
import { useToasts } from '../state/ToastContext';

/** How each writable field is presented, and what it is for. */
const FIELD_LABELS: Record<string, { label: string; help: string }> = {
  llm_provider: { label: 'Provider', help: 'Which adapter answers a question.' },
  llm_base_url: {
    label: 'Base URL',
    help: 'Where the OpenAI-compatible server is. Empty means the adapter’s own default.',
  },
  llm_model: { label: 'Model', help: 'The model id, exactly as the provider spells it.' },
  llm_max_tokens: { label: 'Answer limit', help: 'The most tokens one answer may be.' },
  llm_context_budget: {
    label: 'Context budget',
    help: 'Our own ceiling on a request. Over it, an ask is refused before anything is sent. 0 turns it off.',
  },
  llm_native_tools: {
    label: 'Native tools',
    help: 'Off routes tool declarations through the prompted-JSON fallback. Nothing uses tools in this phase.',
  },
  llm_streaming: { label: 'Streaming', help: 'Off means answers arrive whole rather than word by word.' },
  llm_supports_system: {
    label: 'System prompt',
    help: 'Off folds the instructions into the first message, inside the adapter.',
  },
  llm_max_context: {
    label: 'Declared context window',
    help: 'What this server’s window is, when it is not the adapter’s own. 0 means not declared.',
  },
  llm_stream_usage: {
    label: 'Ask for usage while streaming',
    help: 'Off loses the token counts on a streamed answer — for a server that rejects the field.',
  },
};

/** Settings that are read-only here, in the order they read best. */
const READ_ONLY: (keyof AppSettings)[] = ['data_dir', 'host', 'port', 'log_level', 'web_dist'];

export function SettingsScreen() {
  const { readSettings, writeSettings } = useChat();
  const { push } = useToasts();
  const [document, setDocument] = useState<SettingsDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<SettingsPatch>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const settings = await readSettings(controller.signal);
        if (controller.signal.aborted) return;
        setDocument(settings);
        setError(null);
      } catch (failure: unknown) {
        if (controller.signal.aborted) return;
        setError(describeFailure(failure));
      }
    })();
    return () => controller.abort();
  }, [readSettings]);

  const save = useCallback(async () => {
    if (Object.keys(draft).length === 0) {
      return;
    }
    setSaving(true);
    try {
      const updated = await writeSettings(draft);
      setDocument(updated);
      setDraft({});
      // What is reported is what is **in force**, which is not always what was written: these
      // settings layer defaults < config.yaml < ARCHETYPE_* and this route writes the middle one,
      // so a field also set in the environment is written and then overridden. Saying so here is
      // how the writer finds that out rather than by wondering.
      push('Settings saved. They are in force for the next question.');
    } catch (failure: unknown) {
      push(`Could not save the settings — ${describeFailure(failure)}`, 'error');
    } finally {
      setSaving(false);
    }
  }, [draft, push, writeSettings]);

  if (error !== null) {
    return (
      <p className="chat-context-error" role="alert">
        The settings could not be read — {error}.
      </p>
    );
  }

  if (document === null) {
    return <p className="panel-placeholder">Reading the settings…</p>;
  }

  const settings = document.settings;
  const provider = document.provider;
  const value = <K extends keyof AppSettings>(name: K): AppSettings[K] =>
    (draft as Partial<AppSettings>)[name] ?? settings[name];

  return (
    <div className="settings-screen">
      <h3 className="panel-heading">Assistant</h3>

      <div className={provider.configured ? 'settings-status' : 'settings-status settings-unset'}>
        <p>
          {provider.configured
            ? `Ready — ${provider.provider}, ${provider.model}.`
            : `Not ready — ${provider.reason}`}
        </p>
        <ul className="settings-keys">
          {provider.known_providers.map((name) => (
            <li key={name}>
              <span className="settings-key-name">{name}</span>
              <span className={provider.has_key[name] ? 'settings-key-set' : 'settings-key-unset'}>
                {provider.has_key[name] ? 'key present' : 'no key'}
              </span>
              <span className="settings-key-env">{provider.key_env_vars[name]}</span>
            </li>
          ))}
        </ul>
        <p className="settings-key-note">
          A key is never shown here and can never be set here — it comes from the environment, and
          no route in this application returns one.
        </p>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        {document.writable.map((name) => (
          <SettingField
            key={name}
            name={name}
            value={value(name as keyof AppSettings)}
            providers={provider.known_providers}
            onChange={(next) => setDraft((current) => ({ ...current, [name]: next }))}
          />
        ))}

        <div className="settings-controls">
          <button type="submit" disabled={saving || Object.keys(draft).length === 0}>
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button type="button" disabled={saving} onClick={() => setDraft({})}>
            Revert
          </button>
        </div>
      </form>

      <h3 className="panel-heading">Fixed at startup</h3>
      <p className="settings-fixed-note">
        Changed through the environment or {document.config_file}, and a restart.
      </p>
      <ul className="settings-fixed">
        {READ_ONLY.map((name) => (
          <li key={name}>
            <span className="settings-key-name">{name}</span>
            <span>{String(settings[name] ?? '—')}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface SettingFieldProps {
  name: string;
  value: string | number | boolean | null;
  providers: readonly string[];
  onChange: (value: string | number | boolean) => void;
}

/**
 * One input, chosen by the shape of the value.
 *
 * A boolean is a checkbox, a number is a number box, `llm_provider` is a picker over the
 * registry's own list, and everything else is text. Rendering from the value rather than from a
 * per-field table is what lets `writable` be the server's list: a field added there arrives with
 * an input rather than with a blank space.
 */
function SettingField({ name, value, providers, onChange }: SettingFieldProps) {
  const id = `setting-${name}`;
  const words = FIELD_LABELS[name] ?? { label: name, help: '' };

  if (typeof value === 'boolean') {
    return (
      <div className="setting-field setting-field-check">
        <input
          id={id}
          type="checkbox"
          checked={value}
          onChange={(event) => onChange(event.target.checked)}
        />
        <label htmlFor={id}>{words.label}</label>
        {words.help && <p className="setting-help">{words.help}</p>}
      </div>
    );
  }

  return (
    <div className="setting-field">
      <label htmlFor={id}>{words.label}</label>
      {name === 'llm_provider' ? (
        <select id={id} value={String(value ?? '')} onChange={(event) => onChange(event.target.value)}>
          {providers.map((one) => (
            <option key={one} value={one}>
              {one}
            </option>
          ))}
        </select>
      ) : typeof value === 'number' ? (
        <input
          id={id}
          type="number"
          min={0}
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
        />
      ) : (
        <input
          id={id}
          type="text"
          value={String(value ?? '')}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {words.help && <p className="setting-help">{words.help}</p>}
    </div>
  );
}
