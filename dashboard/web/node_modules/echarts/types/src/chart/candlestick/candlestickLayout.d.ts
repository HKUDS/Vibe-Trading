import { StageHandler } from '../../util/types.js';
import { RectLike } from 'zrender/lib/core/BoundingRect.js';
import { EChartsExtensionInstallRegisters } from '../../extension.js';
export interface CandlestickItemLayout {
    sign: number;
    initBaseline: number;
    ends: number[][];
    brushRect: RectLike;
}
export interface CandlestickLayoutMeta {
    candleWidth: number;
    isSimpleBox: boolean;
}
export declare const candlestickLayout: StageHandler;
export declare function registerCandlestickAxisHandlers(registers: EChartsExtensionInstallRegisters): void;
