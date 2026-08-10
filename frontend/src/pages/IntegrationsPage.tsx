import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  connectIntegration,
  disconnectIntegration,
  listIntegrationOptions,
  listIntegrations,
  updateIntegrationSettings,
} from "../api/client";
import type { IntegrationOption, IntegrationSummary } from "../api/types";
import { useConfig } from "../context/ConfigContext";

type ProviderId = "slack" | "google" | "email_prefs";

interface ProviderDefinition {
  id: ProviderId;
  title: string;
  description: string;
  settingsHint: string;
}

const PROVIDERS: ProviderDefinition[] = [
  {
    id: "slack",
    title: "Slack workspace",
    description: "Let Meeting Assistant post summaries and notifications to channels you choose.",
    settingsHint: "Pick channels where the bot may post. Messages appear as Meeting Assistant, not as you.",
  },
  {
    id: "google",
    title: "Google Calendar",
    description: "Optional read access for availability. Events are created on the assistant calendar and you are invited.",
    settingsHint: "Select calendars the assistant may read for scheduling context.",
  },
  {
    id: "email_prefs",
    title: "Email notifications",
    description: "Choose addresses that receive meeting summaries and action-item digests.",
    settingsHint: "Outbound mail is sent from the Meeting Assistant branded sender, not your personal inbox.",
  },
];

function isConnected(integration: IntegrationSummary | undefined): boolean {
  return integration?.status === "connected";
}

function readStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
}

export function IntegrationsPage() {
  const { config } = useConfig();
  const [searchParams, setSearchParams] = useSearchParams();
  const [integrations, setIntegrations] = useState<IntegrationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyProvider, setBusyProvider] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [optionsByKey, setOptionsByKey] = useState<Record<string, IntegrationOption[]>>({});
  const [draftSettings, setDraftSettings] = useState<Record<string, Record<string, unknown>>>({});

  const loadIntegrations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await listIntegrations(config);
      setIntegrations(response.integrations);
      const nextDrafts: Record<string, Record<string, unknown>> = {};
      for (const integration of response.integrations) {
        nextDrafts[`${integration.provider}:${integration.provider_account_id}`] = {
          ...integration.settings_json,
        };
      }
      setDraftSettings(nextDrafts);
    } catch (loadError) {
      setIntegrations([]);
      setError(loadError instanceof Error ? loadError.message : "Failed to load integrations");
    } finally {
      setLoading(false);
    }
  }, [config]);

  useEffect(() => {
    void loadIntegrations();
  }, [loadIntegrations]);

  useEffect(() => {
    const provider = searchParams.get("provider");
    const status = searchParams.get("status");
    if (provider && status === "connected") {
      setMessage(`${provider} connected successfully.`);
      setSearchParams({}, { replace: true });
      void loadIntegrations();
    }
  }, [loadIntegrations, searchParams, setSearchParams]);

  function findIntegration(providerId: ProviderId): IntegrationSummary | undefined {
    return integrations.find(
      (integration) => integration.provider === providerId && integration.status !== "revoked",
    );
  }

  async function handleConnect(providerId: ProviderId) {
    setBusyProvider(providerId);
    setError(null);
    setMessage(null);

    try {
      const redirectUrl = `${window.location.origin}/settings/integrations`;
      const response = await connectIntegration(config, providerId, redirectUrl);
      if (response.authorize_url) {
        window.location.assign(response.authorize_url);
        return;
      }
      setMessage(`${providerId} connected.`);
      await loadIntegrations();
    } catch (connectError) {
      const detail = connectError instanceof Error ? connectError.message : "Connect failed";
      setError(
        detail.includes("not found")
          ? `${detail} Upload a meeting first to initialize your user account.`
          : detail,
      );
    } finally {
      setBusyProvider(null);
    }
  }

  async function handleDisconnect(providerId: ProviderId, integration: IntegrationSummary) {
    setBusyProvider(providerId);
    setError(null);
    setMessage(null);

    try {
      await disconnectIntegration(config, providerId, integration.provider_account_id);
      setMessage(`${providerId} disconnected.`);
      await loadIntegrations();
    } catch (disconnectError) {
      setError(disconnectError instanceof Error ? disconnectError.message : "Disconnect failed");
    } finally {
      setBusyProvider(null);
    }
  }

  async function ensureOptions(providerId: ProviderId, integration: IntegrationSummary) {
    const key = `${providerId}:${integration.provider_account_id}`;
    if (optionsByKey[key]) {
      return optionsByKey[key];
    }
    const response = await listIntegrationOptions(config, providerId, integration.provider_account_id);
    setOptionsByKey((current) => ({ ...current, [key]: response.options }));
    return response.options;
  }

  async function handleLoadOptions(providerId: ProviderId, integration: IntegrationSummary) {
    setBusyProvider(`${providerId}-options`);
    setError(null);
    try {
      await ensureOptions(providerId, integration);
    } catch (optionsError) {
      setError(optionsError instanceof Error ? optionsError.message : "Failed to load options");
    } finally {
      setBusyProvider(null);
    }
  }

  async function handleSaveSettings(providerId: ProviderId, integration: IntegrationSummary) {
    const key = `${providerId}:${integration.provider_account_id}`;
    const settings = draftSettings[key] ?? integration.settings_json;
    setBusyProvider(`${providerId}-save`);
    setError(null);
    setMessage(null);

    try {
      await updateIntegrationSettings(config, providerId, settings, integration.provider_account_id);
      setMessage(`${providerId} settings saved.`);
      await loadIntegrations();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save settings");
    } finally {
      setBusyProvider(null);
    }
  }

  function updateDraft(key: string, patch: Record<string, unknown>) {
    setDraftSettings((current) => ({
      ...current,
      [key]: { ...current[key], ...patch },
    }));
  }

  function renderSlackSettings(integration: IntegrationSummary) {
    const key = `slack:${integration.provider_account_id}`;
    const draft = draftSettings[key] ?? integration.settings_json;
    const selectedChannels = new Set(readStringList(draft.channels));
    const options = optionsByKey[key] ?? [];

    return (
      <div className="integration-settings">
        <p className="muted">{PROVIDERS.find((item) => item.id === "slack")?.settingsHint}</p>
        <button
          type="button"
          className="secondary"
          disabled={busyProvider === "slack-options"}
          onClick={() => void handleLoadOptions("slack", integration)}
        >
          {busyProvider === "slack-options" ? "Loading channels..." : "Load channels"}
        </button>
        {options.length > 0 && (
          <fieldset className="checkbox-grid">
            <legend>Allowed channels</legend>
            {options.map((option) => (
              <label key={option.id} className="checkbox-row">
                <input
                  type="checkbox"
                  checked={selectedChannels.has(option.label)}
                  onChange={(event) => {
                    const next = new Set(selectedChannels);
                    if (event.target.checked) {
                      next.add(option.label);
                    } else {
                      next.delete(option.label);
                    }
                    updateDraft(key, { channels: Array.from(next) });
                  }}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </fieldset>
        )}
        <button
          type="button"
          disabled={busyProvider === "slack-save"}
          onClick={() => void handleSaveSettings("slack", integration)}
        >
          {busyProvider === "slack-save" ? "Saving..." : "Save Slack settings"}
        </button>
      </div>
    );
  }

  function renderGoogleSettings(integration: IntegrationSummary) {
    const key = `google:${integration.provider_account_id}`;
    const draft = draftSettings[key] ?? integration.settings_json;
    const selectedCalendars = new Set(readStringList(draft.calendar_ids));
    const inviteEmail = typeof draft.invite_email === "string" ? draft.invite_email : "";
    const options = optionsByKey[key] ?? [];

    return (
      <div className="integration-settings">
        <p className="muted">{PROVIDERS.find((item) => item.id === "google")?.settingsHint}</p>
        <label>
          Invite email (attendee on assistant calendar events)
          <input
            value={inviteEmail}
            placeholder="you@company.com"
            onChange={(event) => updateDraft(key, { invite_email: event.target.value.trim() })}
          />
        </label>
        <button
          type="button"
          className="secondary"
          disabled={busyProvider === "google-options"}
          onClick={() => void handleLoadOptions("google", integration)}
        >
          {busyProvider === "google-options" ? "Loading calendars..." : "Load calendars"}
        </button>
        {options.length > 0 && (
          <fieldset className="checkbox-grid">
            <legend>Readable calendars</legend>
            {options.map((option) => (
              <label key={option.id} className="checkbox-row">
                <input
                  type="checkbox"
                  checked={selectedCalendars.has(option.id)}
                  onChange={(event) => {
                    const next = new Set(selectedCalendars);
                    if (event.target.checked) {
                      next.add(option.id);
                    } else {
                      next.delete(option.id);
                    }
                    updateDraft(key, { calendar_ids: Array.from(next) });
                  }}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </fieldset>
        )}
        <button
          type="button"
          disabled={busyProvider === "google-save"}
          onClick={() => void handleSaveSettings("google", integration)}
        >
          {busyProvider === "google-save" ? "Saving..." : "Save calendar settings"}
        </button>
      </div>
    );
  }

  function renderEmailSettings(integration: IntegrationSummary) {
    const key = `email_prefs:${integration.provider_account_id}`;
    const draft = draftSettings[key] ?? integration.settings_json;
    const emails = readStringList(draft.notification_emails).join(", ");
    const notificationsEnabled = draft.notifications_enabled !== false;

    return (
      <div className="integration-settings">
        <p className="muted">{PROVIDERS.find((item) => item.id === "email_prefs")?.settingsHint}</p>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={notificationsEnabled}
            onChange={(event) => updateDraft(key, { notifications_enabled: event.target.checked })}
          />
          <span>Enable email notifications</span>
        </label>
        <label>
          Notification emails
          <input
            value={emails}
            placeholder="you@company.com, team@company.com"
            onChange={(event) =>
              updateDraft(key, {
                notification_emails: event.target.value
                  .split(",")
                  .map((item) => item.trim())
                  .filter(Boolean),
              })
            }
          />
        </label>
        <button
          type="button"
          disabled={busyProvider === "email_prefs-save"}
          onClick={() => void handleSaveSettings("email_prefs", integration)}
        >
          {busyProvider === "email_prefs-save" ? "Saving..." : "Save email preferences"}
        </button>
      </div>
    );
  }

  return (
    <section className="panel">
      <h1>Integrations</h1>
      <p className="lede">
        Connect the channels you want. Outbound actions always appear as{" "}
        <strong>Meeting Assistant</strong> — Slack bot, branded email sender, and assistant-owned calendar invites.
      </p>

      <div className="callout">
        <strong>Actions appear as Meeting Assistant</strong>
        <p className="muted">
          Connecting an integration grants permission for the app to act on your behalf. Messages, emails, and calendar
          events are sent from the Meeting Assistant identity — not from your personal Slack profile or Gmail account.
        </p>
      </div>

      {message && <p className="success">{message}</p>}
      {error && (
        <p className="error">
          {error}{" "}
          {error.includes("initialize your user account") && (
            <Link className="inline-link" to="/">
              Go to Upload →
            </Link>
          )}
        </p>
      )}

      {loading && <p className="muted">Loading integrations...</p>}

      <div className="stack integration-grid">
        {PROVIDERS.map((provider) => {
          const integration = findIntegration(provider.id);
          const connected = isConnected(integration);
          const statusLabel = integration?.status ?? "not_connected";

          return (
            <article key={provider.id} className="result-card integration-card">
              <div className="status-row">
                <h2>{provider.title}</h2>
                <span className={`badge badge-${connected ? "connected" : "pending"}`}>{statusLabel}</span>
              </div>
              <p className="muted">{provider.description}</p>

              {integration?.provider_account_id && integration.provider_account_id !== "" && (
                <p className="muted">Account: {integration.provider_account_id}</p>
              )}

              <div className="button-row">
                {!connected && (
                  <button
                    type="button"
                    disabled={busyProvider === provider.id}
                    onClick={() => void handleConnect(provider.id)}
                  >
                    {busyProvider === provider.id ? "Connecting..." : "Connect"}
                  </button>
                )}
                {connected && integration && (
                  <button
                    type="button"
                    className="danger"
                    disabled={busyProvider === provider.id}
                    onClick={() => void handleDisconnect(provider.id, integration)}
                  >
                    {busyProvider === provider.id ? "Disconnecting..." : "Disconnect"}
                  </button>
                )}
              </div>

              {connected && integration && provider.id === "slack" && renderSlackSettings(integration)}
              {connected && integration && provider.id === "google" && renderGoogleSettings(integration)}
              {connected && integration && provider.id === "email_prefs" && renderEmailSettings(integration)}
            </article>
          );
        })}
      </div>

      {!loading && integrations.length === 0 && !error && (
        <p className="muted">
          No integrations connected yet. If connect fails,{" "}
          <Link className="inline-link" to="/">
            upload a meeting
          </Link>{" "}
          once to create your user record.
        </p>
      )}
    </section>
  );
}
