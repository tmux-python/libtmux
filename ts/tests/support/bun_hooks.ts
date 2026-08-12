import { afterAll } from "bun:test";

import { reapRegisteredFixtures } from "./fixture_registry.js";

afterAll(async () => {
  await reapRegisteredFixtures();
});
