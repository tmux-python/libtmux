export interface TmuxConnectionOptions {
  readonly colors?: 88 | 256;
  readonly configFile?: string;
  readonly environment?: Readonly<Record<string, string | undefined>>;
  readonly executable: string;
  readonly socketName?: string;
  readonly socketPath?: string;
}

export class TmuxConnection {
  readonly colors: 88 | 256 | undefined;
  readonly configFile: string | undefined;
  readonly environment: Readonly<Record<string, string | undefined>>;
  readonly executable: string;
  readonly socketName: string | undefined;
  readonly socketPath: string | undefined;

  constructor(options: TmuxConnectionOptions) {
    if (options.socketName !== undefined && options.socketPath !== undefined) {
      throw new TypeError("socketName and socketPath are mutually exclusive");
    }

    this.colors = options.colors;
    this.configFile = options.configFile;
    this.environment = Object.freeze({ ...options.environment });
    this.executable = options.executable;
    this.socketName = options.socketName;
    this.socketPath = options.socketPath;
    Object.freeze(this);
  }
}
