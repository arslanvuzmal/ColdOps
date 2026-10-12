'use client';

/**
 * System: is ColdOps healthy, and when may cold mail resume?
 *
 * Four sections. Reactivation is the `coldops reactivate` checklist on screen:
 * each mailbox against the inbox bar, and what would go out the moment mail is
 * switched back on. Then every scheduled job with its last and next run, the
 * models the system is learning with, and the personal PDFs.
 *
 * Read-only. Switching mailboxes back on stays a deliberate act.
 */

import React from 'react';
import { Badge, Card, Empty, ErrorNote, Spinner, Stat, Table, Time } from '@/components/crm/ui';
import { useLiveApi } from '@/lib/session';
import { api, type MailboxReadiness, type SystemStatus } from '@/lib/coldops';

function ReadinessRow({ box }: { box: MailboxReadiness }) {
  const rate = box.probes > 0 ? box.inbox / box.probes : null;
  return (
    <tr>
      <td className="px-3 py-2 font-medium text-slate-900">{box.address}</td>
      <td className="px-3 py-2">
        {box.switched_on ? <Badge tone="good">on</Badge> : <Badge tone="neutral">paused</Badge>}
      </td>
      <td className="px-3 py-2 tabular-nums">
        {rate === null ? (
          <Badge tone="neutral">no tests yet</Badge>
        ) : (
          <Badge tone={rate >= 0.8 ? 'good' : rate >= 0.5 ? 'warn' : 'bad'}>
            {box.inbox}/{box.probes} in inbox
          </Badge>
        )}
      </td>
      <td className="px-3 py-2 tabular-nums text-slate-700">{box.days_measured} of 10</td>
      <td className="px-3 py-2 tabular-nums text-slate-700">
        day {box.ramp_day}: {box.cold_limit_today}/day
        <span className="text-slate-400"> of {box.daily_limit}</span>
      </td>
      <td className="px-3 py-2 text-sm">
        {box.ready ? (
          <Badge tone="good">ready</Badge>
        ) : (
          <ul className="space-y-0.5 text-slate-600">
            {box.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
      </td>
    </tr>
  );
}

function Reactivation({ data }: { data: SystemStatus }) {
  const r = data.readiness;
  const total = r.mailboxes.length;
  return (
    <Card
      title="Can cold mail be switched back on?"
      subtitle={`The bar: ${r.bar}.`}
    >
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Mailboxes ready"
          value={`${r.ready} of ${total}`}
          tone={r.ready === total && total > 0 ? 'good' : 'warn'}
        />
        <Stat
          label="Earliest restart"
          value={
            r.earliest
              ? new Date(r.earliest + 'T00:00:00Z').toLocaleDateString(undefined, {
                  day: 'numeric',
                  month: 'short',
                })
              : r.ready === total && total > 0
                ? 'now'
                : '—'
          }
          hint={r.earliest ? 'if every daily inbox test lands' : 'needs more than time'}
        />
        <Stat
          label="Queued, would go out"
          value={`${r.queued}`}
          tone={r.queued_stale > 0 ? 'warn' : 'neutral'}
          hint={`${r.queued_stale} older than ${r.stale_days} days`}
        />
        <Stat
          label="Approved, not queued"
          value={`${r.approved}`}
          tone={r.approved_stale > 0 ? 'warn' : 'neutral'}
          hint={`${r.approved_stale} older than ${r.stale_days} days`}
        />
      </div>
      {total === 0 ? (
        <Empty>No sending mailbox is in any campaign.</Empty>
      ) : (
        <Table head={['Mailbox', 'Cold mail', 'Inbox tests (14d)', 'Days measured', 'Ramp', 'Status']}>
          {r.mailboxes.map((box) => (
            <ReadinessRow key={box.address} box={box} />
          ))}
        </Table>
      )}
      {r.blockers.length > 0 || r.notes.length > 0 ? (
        <ul className="mt-3 space-y-1 text-sm">
          {r.blockers.map((b) => (
            <li key={b} className="text-rose-700">
              Not yet: {b}
            </li>
          ))}
          {r.notes.map((n) => (
            <li key={n} className="text-amber-700">
              Note: {n}
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
}

function Jobs({ data }: { data: SystemStatus }) {
  const s = data.schedules;
  return (
    <Card
      title="Scheduled jobs"
      subtitle="Everything ColdOps does on its own, on a clock. Asked of the scheduler directly."
    >
      {!s.reachable ? (
        <ErrorNote error={`The scheduler did not answer: ${s.error ?? 'unknown error'}`} />
      ) : s.schedules.length === 0 ? (
        <Empty>No scheduled jobs are installed for this workspace.</Empty>
      ) : (
        <Table head={['Job', 'What it does', 'State', 'Last run', 'Next run']}>
          {s.schedules.map((job) => (
            <tr key={job.name}>
              <td className="px-3 py-2 font-medium text-slate-900">{job.name}</td>
              <td className="px-3 py-2 text-sm text-slate-600">{job.note ?? job.workflow}</td>
              <td className="px-3 py-2">
                {job.paused ? <Badge tone="warn">paused</Badge> : <Badge tone="good">running</Badge>}
              </td>
              <td className="px-3 py-2 text-slate-600">
                {job.last_run ? <Time value={job.last_run} /> : 'never'}
              </td>
              <td className="px-3 py-2 text-slate-600">
                {job.next_run ? <Time value={job.next_run} /> : '—'}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

const GOOD_ACTIONS: Record<string, string> = {
  restarted: 'repaired',
  pruned: 'disk cleared',
  backed_up: 'backed up',
};

function Healing({ data }: { data: SystemStatus }) {
  const h = data.healing;
  return (
    <Card
      title="Self-healing and backups"
      subtitle="What repaired itself. Stuck scheduled jobs are reinstalled; a container stuck unhealthy is restarted, at most three times an hour, then left for you; old build cache is cleared when the disk passes 80%; the database is backed up daily. Deploys and data are never touched."
    >
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Repaired (7 days)" value={`${h.repaired_7d}`} tone="good" />
        <Stat
          label="Last database backup"
          value={h.last_backup_at ? new Date(h.last_backup_at).toLocaleDateString() : 'none yet'}
          tone={h.last_backup_at ? 'good' : 'warn'}
          hint="daily at 03:30 UTC, kept for a week"
        />
        <Stat
          label="Gave up, needs you (7 days)"
          value={`${h.gave_up_7d}`}
          tone={h.gave_up_7d > 0 ? 'bad' : 'neutral'}
        />
        <Stat
          label="Container doctor"
          value={h.container_log_available ? 'installed' : 'not installed'}
          tone={h.container_log_available ? 'good' : 'warn'}
          hint={h.container_log_available ? 'checks every two minutes' : 'run deploy/install-healing.sh on the server'}
        />
      </div>
      {h.recent.length === 0 ? (
        <Empty>Nothing has needed repairing.</Empty>
      ) : (
        <Table head={['When', 'What', 'Action', 'Why']}>
          {h.recent.map((r, i) => (
            <tr key={`${r.at}-${i}`}>
              <td className="px-3 py-2 text-slate-600">
                <Time value={r.at} />
              </td>
              <td className="px-3 py-2 text-slate-900">{r.what}</td>
              <td className="px-3 py-2">
                <Badge tone={GOOD_ACTIONS[r.action] ? 'good' : 'bad'}>
                  {GOOD_ACTIONS[r.action] ?? r.action.replace('_', ' ')}
                </Badge>
              </td>
              <td className="px-3 py-2 text-sm text-slate-600">{r.reason}</td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

function Models({ data }: { data: SystemStatus }) {
  return (
    <Card
      title="Models"
      subtitle={`What ColdOps is learning with. A shadow model only watches; it decides nothing until it beats the live one and you approve it. ${data.labels_total} labelled examples so far.`}
    >
      {data.models.length === 0 ? (
        <Empty>No model is registered yet.</Empty>
      ) : (
        <Table head={['Model', 'Version', 'Role', 'Readings (7 days)', 'Readings (all)']}>
          {data.models.map((m) => (
            <tr key={`${m.name}:${m.version}`}>
              <td className="px-3 py-2 font-medium text-slate-900">{m.name.replace(/_/g, ' ')}</td>
              <td className="px-3 py-2 font-mono text-xs text-slate-600">{m.version}</td>
              <td className="px-3 py-2">
                <Badge tone={m.status === 'active' ? 'good' : m.status === 'shadow' ? 'info' : 'neutral'}>
                  {m.status === 'active' ? 'live' : m.status}
                </Badge>
              </td>
              <td className="px-3 py-2 tabular-nums">{m.predictions_7d}</td>
              <td className="px-3 py-2 tabular-nums">{m.predictions_total}</td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

function share(hit: number, of: number): string {
  return of > 0 ? `${hit}/${of} (${Math.round((hit / of) * 100)}%)` : 'no tests yet';
}

function Pdfs({ data }: { data: SystemStatus }) {
  const p = data.pdfs;
  const withRate = p.probes_with_pdf > 0 ? p.inbox_with_pdf / p.probes_with_pdf : null;
  const withoutRate = p.probes_without_pdf > 0 ? p.inbox_without_pdf / p.probes_without_pdf : null;
  const hurts = withRate !== null && withoutRate !== null && withRate + 0.1 < withoutRate;
  return (
    <Card
      title="Personal PDFs"
      subtitle="The one-page check of their own site that goes with a business's first email."
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Switched" value={p.enabled ? 'on' : 'off'} tone={p.enabled ? 'good' : 'warn'} />
        <Stat
          label="Rendered (7 days)"
          value={p.rendered_7d === null ? '—' : `${p.rendered_7d}`}
          hint={p.rendered_total === null ? 'storage not mounted here' : `${p.rendered_total} in all`}
        />
        <Stat label="First emails (7 days)" value={`${p.first_emails_7d}`} />
        <Stat
          label="Carried a PDF"
          value={`${p.attached_7d}`}
          hint={
            p.first_emails_7d > 0
              ? `${Math.round((p.attached_7d / p.first_emails_7d) * 100)}% of first emails`
              : 'no first emails this week'
          }
        />
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Stat
          label="Inbox tests WITH the PDF (14 days)"
          value={share(p.inbox_with_pdf, p.probes_with_pdf)}
          tone={withRate === null ? 'neutral' : withRate >= 0.8 ? 'good' : 'bad'}
          hint="half of each day's inbox tests carry your own PDF"
        />
        <Stat
          label="Inbox tests WITHOUT it"
          value={share(p.inbox_without_pdf, p.probes_without_pdf)}
          tone={withoutRate === null ? 'neutral' : withoutRate >= 0.8 ? 'good' : 'bad'}
          hint={
            hurts
              ? 'the PDF is costing inbox placement: consider switching it off'
              : 'the comparison that says whether the attachment hurts'
          }
        />
      </div>
    </Card>
  );
}

export default function SystemPage() {
  const { data, error, loading, reload } = useLiveApi((t) => api.system(t), 120_000);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">System</h1>
        <p className="mt-1 text-sm text-slate-500">
          When cold mail can resume, what runs on its own, what the system is learning, and the
          personal PDFs. Read-only; checked every two minutes.
        </p>
      </div>
      {error ? (
        <ErrorNote error={error} onRetry={reload} />
      ) : loading && !data ? (
        <Spinner />
      ) : data ? (
        <>
          <Reactivation data={data} />
          <Jobs data={data} />
          <Healing data={data} />
          <Models data={data} />
          <Pdfs data={data} />
        </>
      ) : null}
    </div>
  );
}
