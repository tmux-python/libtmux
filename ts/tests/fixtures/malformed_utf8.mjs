const chunks = [
  Buffer.from([0x76, 0x61, 0x6c, 0x69, 0x64, 0x3a, 0xe2]),
  Buffer.from([0x82]),
  Buffer.from([0xac, 0x0a, 0x62, 0x61, 0x64, 0x3a, 0xff, 0xc3]),
  Buffer.from([0x28, 0x0a]),
];

async function writeChunks(index = 0) {
  const chunk = chunks[index];
  if (chunk === undefined) return;
  process.stdout.write(chunk);
  await new Promise((resolve) => setImmediate(resolve));
  await writeChunks(index + 1);
}

await writeChunks();
