import { TestServer, type TestServerOptions } from "../../src/_internal/test/test_server.js";

const fixtures = new Set<TestServer>();

export async function createRegisteredTestServer(options: TestServerOptions): Promise<TestServer> {
  const server = await TestServer.create(options);
  fixtures.add(server);
  return server;
}

export async function reapRegisteredFixtures(): Promise<void> {
  const owned = [...fixtures];
  fixtures.clear();
  const outcomes = await Promise.allSettled(owned.map((server) => server.dispose()));
  const failures = outcomes.flatMap((outcome) =>
    outcome.status === "rejected" ? [String(outcome.reason)] : [],
  );
  if (failures.length > 0) throw new Error(`worker fixture cleanup failed: ${failures.join("; ")}`);
}
