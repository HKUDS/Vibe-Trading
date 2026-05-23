import ComponentModel from '../../model/Component.js';
import { BoxLayoutOptionMixin, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin, ComponentOption, ItemStyleOption, NullUndefined } from '../../util/types.js';
import { ThumbnailBridgeImpl } from './ThumbnailBridgeImpl.js';
/**
 * [NOTE]: thumbnail is implemented as a component, rather than internal data strucutrue,
 *  due to the possibility of serveing geo and related series with a single thumbnail,
 *  and enable to apply some common layout feature, such as matrix coord sys.
 */
export interface ThumbnailOption extends ComponentOption, BoxLayoutOptionMixin, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin {
    mainType?: 'thumbnail';
    show?: boolean;
    itemStyle?: ItemStyleOption;
    windowStyle?: ItemStyleOption;
    seriesIndex?: number | number[];
    seriesId?: string | string[];
}
export interface ThumbnailZ2Setting {
    background: number;
    window: number;
}
export declare class ThumbnailModel extends ComponentModel<ThumbnailOption> {
    static type: "thumbnail";
    type: "thumbnail";
    static layoutMode: "box";
    preventAutoZ: boolean;
    static dependencies: string[];
    static defaultOption: ThumbnailOption;
    private _birdge;
    private _target;
    optionUpdated(newCptOption: ThumbnailOption, isInit: boolean): void;
    private _updateBridge;
    shouldShow(): boolean;
    getBridge(): ThumbnailBridgeImpl;
    getTarget(): {
        baseMapProvider: ComponentModel | NullUndefined;
    };
}
