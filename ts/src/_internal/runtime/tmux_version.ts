export interface TmuxVersion {
  readonly major: number;
  readonly minor: number;
  readonly raw: string;
  readonly suffix: string;
}

const taggedVersionPattern = /^(0|[1-9]\d*)\.(0|[1-9]\d*)([a-z]?)$/u;
const masterBasePattern = /(0|[1-9]\d*)\.(0|[1-9]\d*)([a-z]?)/u;

function invalidVersion(raw: string): TypeError {
  return new TypeError(`invalid tmux version: ${raw}`);
}

export function parseTmuxVersion(raw: string): TmuxVersion {
  if (raw.includes("master")) {
    const match = masterBasePattern.exec(raw);
    return Object.freeze({
      major: match === null ? 0 : Number.parseInt(match[1]!, 10),
      minor: match === null ? 0 : Number.parseInt(match[2]!, 10),
      raw,
      suffix: match?.[3] ?? "",
    });
  }

  const match = taggedVersionPattern.exec(raw);
  if (match === null) throw invalidVersion(raw);
  return Object.freeze({
    major: Number.parseInt(match[1]!, 10),
    minor: Number.parseInt(match[2]!, 10),
    raw,
    suffix: match[3]!,
  });
}

export function compareTmuxVersions(left: TmuxVersion, right: TmuxVersion): number {
  const leftMaster = left.raw.includes("master");
  const rightMaster = right.raw.includes("master");
  if (leftMaster !== rightMaster) return leftMaster ? 1 : -1;
  if (left.major !== right.major) return left.major - right.major;
  if (left.minor !== right.minor) return left.minor - right.minor;
  return left.suffix.localeCompare(right.suffix, "en-US");
}

export function tmuxVersionAtLeast(version: TmuxVersion, minimum: TmuxVersion): boolean {
  return compareTmuxVersions(version, minimum) >= 0;
}

export function tmuxVersionIsExact(version: TmuxVersion, expected: TmuxVersion): boolean {
  return version.raw === expected.raw;
}
