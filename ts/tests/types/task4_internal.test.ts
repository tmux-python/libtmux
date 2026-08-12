import {
  beginFixtureLaunch,
  promoteFixtureLaunch,
  rollbackFixtureLaunchNotStarted,
  type ControllerIdentity,
  type DaemonIdentity,
  type FixtureRecord,
  type LaunchAttemptCapability,
  type LaunchGeneration,
  type ProcessIdentity,
  type ReservationCapability,
  type SocketIdentity,
} from "../../src/_internal/test/run_root.js";
import type {
  TestServerOptions,
  TestServerRequestSnapshot,
} from "../../src/_internal/test/test_server.js";

declare const capability: ReservationCapability;
declare const attempt: LaunchAttemptCapability;
declare const controller: ControllerIdentity;
declare const daemon: DaemonIdentity;
declare const generation: LaunchGeneration;
declare const owner: ProcessIdentity;
declare const socketIdentity: SocketIdentity;
declare const launchingRecord: Extract<FixtureRecord, { readonly phase: "launching" }>;
declare const requestSnapshot: TestServerRequestSnapshot;

const base = {
  controller,
  logicalSocketName: "t-test-00000000-000",
  owner,
  protocol: "libtmux-test-fixture-v3" as const,
  runId: "00000000-0000-4000-8000-000000000000",
  socketPath: "/tmp/run/t-test-00000000-000/s",
};
const bootstrapArgv = ["/usr/bin/tmux", "-f", "/dev/null"] as const;

void ({
  launchExecutable: "/tmp/tmux-launch-wrapper",
  requestObserver: (_request: TestServerRequestSnapshot) => undefined,
  runRoot: "/tmp/run",
  tmuxExecutable: "/usr/bin/tmux",
} satisfies TestServerOptions);

void ({ ...base, phase: "reserved" } satisfies FixtureRecord);
void ({ ...base, bootstrapArgv, generation, phase: "launching" } satisfies FixtureRecord);
void ({
  ...base,
  bootstrapArgv,
  daemon,
  generation,
  phase: "running",
  socketIdentity,
} satisfies FixtureRecord);

// @ts-expect-error reserved records cannot carry launch generation authority.
void ({ ...base, generation, phase: "reserved" } satisfies FixtureRecord);

// @ts-expect-error reserved records cannot carry bootstrap argv authority.
void ({ ...base, bootstrapArgv, phase: "reserved" } satisfies FixtureRecord);

// @ts-expect-error reserved records cannot carry socket unlink authority.
void ({ ...base, phase: "reserved", socketIdentity } satisfies FixtureRecord);

// @ts-expect-error reserved records cannot carry daemon authority.
void ({ ...base, daemon, phase: "reserved" } satisfies FixtureRecord);

// @ts-expect-error launching records require the immutable generation.
void ({ ...base, bootstrapArgv, phase: "launching" } satisfies FixtureRecord);

// @ts-expect-error launching records require the immutable bootstrap argv.
void ({ ...base, generation, phase: "launching" } satisfies FixtureRecord);

// @ts-expect-error launching records cannot carry daemon authority.
void ({ ...base, bootstrapArgv, daemon, generation, phase: "launching" } satisfies FixtureRecord);

void ({
  ...base,
  bootstrapArgv,
  generation,
  phase: "launching",
  // @ts-expect-error launching records cannot carry socket unlink authority.
  socketIdentity,
} satisfies FixtureRecord);

void ({
  ...base,
  bootstrapArgv,
  generation,
  phase: "running",
  socketIdentity,
  // @ts-expect-error running records require daemon identity.
} satisfies FixtureRecord);

// @ts-expect-error running records require socket identity.
void ({ ...base, bootstrapArgv, daemon, generation, phase: "running" } satisfies FixtureRecord);

// @ts-expect-error running records require the immutable launch generation.
void ({ ...base, bootstrapArgv, daemon, phase: "running", socketIdentity } satisfies FixtureRecord);

// @ts-expect-error running records require the immutable bootstrap argv.
void ({ ...base, daemon, generation, phase: "running", socketIdentity } satisfies FixtureRecord);

void beginFixtureLaunch(capability, { bootstrapArgv, generation });
void rollbackFixtureLaunchNotStarted(attempt);
void promoteFixtureLaunch(attempt, daemon.pid);

// @ts-expect-error launch generations are immutable after entry snapshot.
launchingRecord.generation.value = "22222222-2222-4222-8222-222222222222";

// @ts-expect-error complete bootstrap argv is immutable after entry snapshot.
launchingRecord.bootstrapArgv.push("changed");

// @ts-expect-error observed request argv is an immutable execution snapshot.
requestSnapshot.args.push("changed");

// @ts-expect-error observed request environment is immutable after entry snapshot.
requestSnapshot.environment.PATH = "changed";

const forgedReservation = {
  recordPath: "/tmp/run/t-test-00000000-000/fixture.json",
  reservationPath: "/tmp/run/t-test-00000000-000",
  runId: "00000000-0000-4000-8000-000000000000",
  runRoot: "/tmp/run",
};

// @ts-expect-error a structurally complete reservation is not an opaque capability.
void beginFixtureLaunch(forgedReservation, { bootstrapArgv, generation });

const forgedAttempt = {
  attemptId: "33333333-3333-4333-8333-333333333333",
  recordPath: forgedReservation.recordPath,
  reservationPath: forgedReservation.reservationPath,
  runId: forgedReservation.runId,
  runRoot: forgedReservation.runRoot,
};

// @ts-expect-error a structurally complete launch attempt is not an opaque capability.
void rollbackFixtureLaunchNotStarted(forgedAttempt);

// @ts-expect-error launch transitions obtain controller authority from the reservation.
void beginFixtureLaunch(capability, { bootstrapArgv, controller, generation });

// @ts-expect-error launch transitions do not accept an executable override.
void beginFixtureLaunch(capability, { bootstrapArgv, generation, tmuxExecutable: "tmux" });

// @ts-expect-error fixture v3 records do not persist the legacy executable field.
void ({ ...base, phase: "reserved", tmuxExecutable: "tmux" } satisfies FixtureRecord);

// @ts-expect-error rollback requires the exact opaque launch-attempt capability.
void rollbackFixtureLaunchNotStarted(capability);

// @ts-expect-error promotion requires the exact opaque launch-attempt capability.
void promoteFixtureLaunch(capability, daemon.pid);

// @ts-expect-error promotion cannot replace the launch attempt's generation snapshot.
void promoteFixtureLaunch(attempt, daemon.pid, { generation });
