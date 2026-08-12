export {};

declare global {
  type ConnectionOptions = import("node:tls").ConnectionOptions;
  type KeyObject = import("node:tls").KeyObject;
  type TLSSocket = import("node:tls").TLSSocket;
}

declare module "node:util" {
  interface TextEncoderEncodeIntoResult {
    read: number;
    written: number;
  }
}
