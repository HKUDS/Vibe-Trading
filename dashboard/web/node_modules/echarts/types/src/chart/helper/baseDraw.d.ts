import type Group from 'zrender/lib/graphic/Group.js';
import type Element from 'zrender/lib/Element.js';
import { CoordinateSystemClipArea } from '../../coord/CoordinateSystem.js';
import type SeriesData from '../../data/SeriesData.js';
import type Model from '../../model/Model.js';
import { AnimationOptionMixin, ColorString, DefaultEmphasisFocus, ItemStyleOption, LabelOption, LineLabelOption, LineStyleOption, StageHandlerProgressParams, StatesOptionMixin, SymbolOptionMixin, ZRColor } from '../../util/types.js';
import type Displayable from 'zrender/lib/graphic/Displayable.js';
export interface ISymbolDraw {
    group: Group;
    updateData(data: ListForSymbolDraw, opt?: SymbolDrawUpdateOpt): void;
    incrementalPrepareUpdate(data: ListForSymbolDraw): void;
    incrementalUpdate(taskParams: StageHandlerProgressParams, data: ListForSymbolDraw, incrementalId: Displayable['incremental'], opt?: SymbolDrawUpdateOpt): void;
    /**
     * NOTICE: `updateLayout` only works for the result of `updateData`.
     * The caller should ensure `updateLayout` to not be called if the result
     * does not exists or cleared by `incrementalPrepareUpdate` or `remove`.
     */
    updateLayout(opt?: SymbolDrawUpdateOpt): void;
    eachRendered(cb: (el: Element) => boolean | void): void;
    /**
     * It is typicall called on `ChartView['remove']` or `ChartView['dispose']`.
     */
    remove(enableAnimation?: boolean): void;
}
export interface SymbolDrawUpdateOpt {
    isIgnore?(idx: number): boolean;
    clipShape?: CoordinateSystemClipArea;
    getSymbolPoint?(idx: number): number[];
    disableAnimation?: boolean;
}
interface SymbolDrawStateOption {
    itemStyle?: ItemStyleOption;
    label?: LabelOption;
}
export declare type ListForSymbolDraw = SeriesData<Model<SymbolDrawItemModelOption & AnimationOptionMixin>>;
export interface SymbolDrawItemModelOption extends SymbolOptionMixin<object>, StatesOptionMixin<SymbolDrawStateOption, {
    emphasis?: {
        focus?: DefaultEmphasisFocus;
        scale?: boolean | number;
    };
}>, SymbolDrawStateOption {
    cursor?: string;
    rippleEffect?: RippleEffectOption;
}
interface RippleEffectOption {
    period?: number;
    /**
     * Scale of ripple
     */
    scale?: number;
    brushType?: 'fill' | 'stroke';
    color?: ZRColor;
    /**
     * ripple number
     */
    number?: number;
}
export interface ILineDraw {
    group: Group;
    updateData(lineData: ListForLineDraw): void;
    incrementalPrepareUpdate(lineData: ListForLineDraw): void;
    incrementalUpdate(taskParams: StageHandlerProgressParams, lineData: ListForLineDraw, incrementalId: Displayable['incremental']): void;
    /**
     * NOTICE: `updateLayout` only works for the result of `updateData`.
     * The caller should ensure `updateLayout` to not be called if the result
     * does not exists or cleared by `incrementalPrepareUpdate` or `remove`.
     */
    updateLayout?: () => void;
    eachRendered(cb: (el: Element) => boolean | void): void;
    /**
     * It is typicall called on `ChartView['remove']` or `ChartView['dispose']`.
     */
    remove(): void;
}
export declare type ListForLineDraw = SeriesData<Model<LineDrawModelOption & AnimationOptionMixin>>;
interface LineDrawStateOption {
    lineStyle?: LineStyleOption;
    label?: LineLabelOption;
}
export interface LineDrawModelOption extends LineDrawStateOption, StatesOptionMixin<LineDrawStateOption, {
    emphasis?: {
        focus?: DefaultEmphasisFocus;
    };
}> {
    effect?: {
        show?: boolean;
        period?: number;
        delay?: number | ((idx: number) => number);
        /**
         * If move with constant speed px/sec
         * period will be ignored if this property is > 0,
         */
        constantSpeed?: number;
        symbol?: string;
        symbolSize?: number | number[];
        loop?: boolean;
        roundTrip?: boolean;
        /**
         * Length of trail, 0 - 1
         */
        trailLength?: number;
        /**
         * Default to be same with lineStyle.color
         */
        color?: ColorString;
    };
}
export {};
