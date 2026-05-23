import { EChartsExtensionInstallRegisters } from '../../extension.js';
export interface BoxplotItemLayout {
    ends: number[][];
    initBaseline: number;
}
export declare const boxplotLayoutStageHandler: import("../../util/types").StageHandler;
export declare function registerBoxplotAxisHandlers(registers: EChartsExtensionInstallRegisters): void;
