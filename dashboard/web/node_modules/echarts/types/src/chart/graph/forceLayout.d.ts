export interface ForceLayoutInstance {
    step(cb: (stopped: boolean) => void): void;
    warmUp(): void;
    setFixed(idx: number): void;
    setUnfixed(idx: number): void;
}
export declare const graphForceLayoutStageHandler: import("../../util/types").StageHandler;
