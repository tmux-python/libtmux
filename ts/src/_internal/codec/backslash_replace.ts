function escapeByte(byte: number): string {
  return `\\x${byte.toString(16).padStart(2, "0")}`;
}

function sequenceLength(lead: number): number {
  if (lead <= 0x7f) return 1;
  if (lead >= 0xc2 && lead <= 0xdf) return 2;
  if (lead >= 0xe0 && lead <= 0xef) return 3;
  if (lead >= 0xf0 && lead <= 0xf4) return 4;
  return 0;
}

function validContinuation(lead: number, byte: number, offset: number): boolean {
  if (byte < 0x80 || byte > 0xbf) return false;
  if (offset !== 1) return true;
  if (lead === 0xe0) return byte >= 0xa0;
  if (lead === 0xed) return byte <= 0x9f;
  if (lead === 0xf0) return byte >= 0x90;
  if (lead === 0xf4) return byte <= 0x8f;
  return true;
}

function decodeSequence(bytes: readonly number[]): string {
  if (bytes.length === 1) return String.fromCodePoint(bytes[0]!);
  let codePoint = bytes[0]! & (0x7f >> bytes.length);
  for (const byte of bytes.slice(1)) codePoint = (codePoint << 6) | (byte & 0x3f);
  return String.fromCodePoint(codePoint);
}

export class BackslashReplaceDecoder {
  #ended = false;
  #pending: number[] = [];

  write(chunk: Uint8Array): string {
    if (this.#ended) throw new TypeError("decoder has ended");
    return this.#decode([...this.#pending, ...chunk], false);
  }

  end(chunk: Uint8Array = new Uint8Array()): string {
    if (this.#ended) throw new TypeError("decoder has ended");
    this.#ended = true;
    return this.#decode([...this.#pending, ...chunk], true);
  }

  #decode(bytes: number[], final: boolean): string {
    this.#pending = [];
    let decoded = "";
    let index = 0;

    while (index < bytes.length) {
      const lead = bytes[index]!;
      const length = sequenceLength(lead);
      if (length === 0) {
        decoded += escapeByte(lead);
        index += 1;
        continue;
      }

      const available = Math.min(length, bytes.length - index);
      let prefixIsValid = true;
      for (let offset = 1; offset < available; offset += 1) {
        if (!validContinuation(lead, bytes[index + offset]!, offset)) {
          prefixIsValid = false;
          break;
        }
      }
      if (!prefixIsValid) {
        decoded += escapeByte(lead);
        index += 1;
        continue;
      }

      if (available < length) {
        if (final) {
          decoded += bytes.slice(index).map(escapeByte).join("");
        } else {
          this.#pending = bytes.slice(index);
        }
        break;
      }

      decoded += decodeSequence(bytes.slice(index, index + length));
      index += length;
    }

    return decoded;
  }
}

export function decodeBackslashReplace(bytes: Uint8Array): string {
  return new BackslashReplaceDecoder().end(bytes);
}
